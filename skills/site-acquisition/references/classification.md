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
