# Site and page classification

Classification is the anti-false-positive mechanism for the whole
marketplace. Checks declare the page types they apply to; anything else is
recorded as `not_applicable` rather than fired.

Reporting "no Product schema" on an about page is the commonest way an audit
loses credibility with the person reading it. One visible false positive
causes a reader to discount the other findings too.

## Page types

`home`, `product`, `category`, `article`, `documentation`, `contact`,
`about`, `legal`, `listing`, `other`.

## Signal precedence

1. **Declared schema.org type.** Strongest signal when present — the site is
   telling you what the page is.
2. **URL shape.** Path segment patterns. Reliable but not decisive: `/shop/`
   appears on both listing and detail pages.
3. **Structural evidence.** Price patterns, cart language, internal link
   density, heading count. Used to confirm or override a weak URL guess — for
   example, many links plus repeated prices and no cart language reads as a
   category listing rather than a product detail page.
4. **Content shape fallback** when the URL is uninformative.

### When the URL is explicit, structural evidence does not overrule it

A path segment of `collections` or `category` is not a weak guess — it is the
site stating the page's role. Structural evidence may only *refine* it.

This distinction was learned the expensive way. Storefront grids show a price
on every tile and, on most themes, a quick-add control on every tile too. A
shared "has cart language or has prices → product" rule therefore promoted
every `/collections/` page to `product`, and the structured-data check then
reported "no Product schema" on a listing — which correctly has none, because
forty items is an `ItemList`, not a `Product`. Since `/collections/` is the
default path of the most widely used commerce platform, this misfired on a
large share of exactly the sites the audit is most often pointed at.

The rule now runs in both directions and each needs decisive evidence to move:

- a `category` URL becomes `product` only where the page is genuinely a single
  item — cart control, few onward links, few sections;
- a `product` URL becomes `category` only where it is a dense listing — many
  links and repeated prices with no cart control.

## Site types

`ecommerce`, `local-business`, `software`, `publisher`, `documentation`,
`portfolio`, `unknown`. Derived from the distribution of page types, declared
schema types across the site, and content signals.

Site type gates whole checks. `EC-NAP-INCOMPLETE` runs only for
`local-business`, because name-address-phone consistency is not a meaningful
demand on a SaaS product.

## Generalisation rule

Classification uses schema types, URL shape and structural evidence only.
It must never use a string tied to a particular site, CMS, theme or vendor.
Any pattern that would only match sites you personally studied is overfitting
and will fail on the unseen sites this marketplace is judged against.

When a page genuinely cannot be classified, `other` is correct. Most checks
skip `other`, which is the safe direction to fail in: a missed finding costs
less than a false one.

## Home detection under locale/geo redirects

The home page is not always at `/`. Sites routinely redirect `/` to a locale
path — `/in`, `/en-us`, `/en-gb` — and matching only `path == "/"` on the
*final* URL would then misfile the home page as `other`, silently suppressing
every home-gated check (`AE-NO-DEFINITION`, home-page structured data, home
importance weighting). So a page is treated as `home` when it is the bare
root, when its request URL was the crawl seed root, or when its final path is
just a short locale segment (`/xx` or `/xx-yy`). Locale prefixes are likewise
stripped before URL-shape matching, so `/in/legal` still classifies as legal.

## Representative sampling (why the crawl does not just take the first N)

Classification is only as good as the sample it runs on. Two site shapes break
a naive breadth-first crawl, and the acquisition step defends against both:

- **Section-clustered sitemaps.** A sitemap is frequently grouped by section,
  and a partition can be *entirely* one section (a real example: a large
  payments site whose first sitemap partition is 195/200 legal pages). A
  strict FIFO drains the whole page budget into that one section and the audit
  then "sees" a site that is all legal boilerplate. The crawler interleaves
  sitemap URLs across first-path-segment buckets (`diversify`) so an early,
  capped crawl stays spread across the site.
- **One template dominating.** Even diversified, one type can flood the
  sample. A per-type quota caps how many pages of each type are *kept*
  (`TYPE_QUOTA_SHARE`), with a tighter cap for low-value types (`legal`,
  `other`). A URL whose type is already saturated is skipped *before* it is
  fetched, using a URL-only type guess, so the budget is spent discovering
  variety rather than re-confirming the same template.

Both mechanisms are deterministic: buckets are visited in first-seen order,
entries keep their order within a bucket, and the quota is applied in crawl
order. Two runs over the same site sample the same pages. Redirect targets are
de-duplicated by final URL, so a page reachable under several aliases is
counted once and never inflates a prevalence ratio.
