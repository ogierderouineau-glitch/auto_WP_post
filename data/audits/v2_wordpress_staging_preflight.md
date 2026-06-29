# V2 WordPress Staging Preflight

- Date: 2026-06-25
- Target: `https://staging.flairlab.de`
- Workbook SHA-256: `6db9ba5d8ff8a43d20d8749076e33c9908a69d4a9b046bd95124671d7baac040`
- Post type: `event`
- Result: **not ready for V2 publication**

## Passed

- WordPress authentication succeeded.
- User `Ogier` (ID 12) has administrator role.
- No required upload/edit/publish capability is missing.
- Required category `auto event post` exists as term ID 3554.
- Post REST route exposes ACF and meta objects.
- Core V2 ACF destinations including `hero_h1`, `verlauf_h2`, `fakten` and
  `verlauf_text` are exposed.
- Focus keyword, SEO title and meta description resolve dynamically to their
  exposed underscore-prefixed REST meta keys.

## Blocking destination mismatches

1. ACF field `related_links_html` is not exposed by the staging post REST schema.
2. Yoast destination `yoast_wpseo_opengraph_title` is not exposed.
3. Yoast destination `yoast_wpseo_opengraph_description` is not exposed.

The V2 WordPress provider now checks these destinations before creating or
updating a post, so publication fails safely before mutation.

## Required WordPress-side resolution

- Add/enable the real ACF field `related_links_html` for the Event post field
  group and expose it through REST.
- Confirm the intended Yoast/Open Graph persistence keys.
- Either expose the workbook destination keys through REST and confirm Yoast
  consumes them, or revise the workbook destinations to the actual registered
  keys and revalidate V5.

Do not map `related_links_html` to `gallery_html`; they represent different
payload fields.

## Deployment status

The compatibility plugin is not currently present on staging. WordPress
application-password authentication works for REST but not for the browser
`wp-admin` plugin upload page. One manual package upload is therefore required.
After upload, REST activation can be performed with
`tools/v2_activate_wordpress_plugin.py --activate`.
