# FLAIRLAB V2 REST Compatibility

This WordPress plugin resolves the three staging preflight blockers without
weakening the workbook contract:

- adds the real ACF field `related_links_html`;
- exposes `yoast_wpseo_opengraph_title` through REST;
- exposes `yoast_wpseo_opengraph_description` through REST;
- synchronizes the friendly REST keys to Yoast native Open Graph meta keys.

## Install on staging

1. Copy `flairlab-v2-rest-compat` into `wp-content/plugins/`.
   Alternatively upload `dist/flairlab-v2-rest-compat.zip` in WordPress Admin.
2. Activate **FLAIRLAB V2 REST Compatibility**.
3. Confirm ACF Pro and Yoast SEO are active.
4. Run the read-only preflight:

```bash
myenv/bin/python tools/v2_wordpress_preflight.py \
  data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm \
  --output data/audits/v2_wordpress_staging_preflight.json
```

The report must return `"ready": true` before V2 publication is enabled.

After the package has been uploaded, activation can also be done through the
authenticated REST API:

```bash
myenv/bin/python tools/v2_activate_wordpress_plugin.py --activate
```

Running the command without `--activate` is read-only.

## Notes

- The ACF field is registered as local PHP configuration so its name and REST
  exposure cannot drift from the V2 workbook.
- `related_links_html` is intentionally separate from `gallery_html`.
- No WordPress installation or activation is performed automatically by this repository.
