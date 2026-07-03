# FLAIRLAB V2 REST Compatibility

This WordPress plugin resolves staging Yoast/Open Graph REST compatibility
without weakening the workbook contract:

- exposes `yoast_wpseo_opengraph_title` through REST;
- exposes `yoast_wpseo_opengraph_description` through REST;
- synchronizes the friendly REST keys to Yoast native Open Graph meta keys.

## Install on staging

1. Copy `flairlab-v2-rest-compat` into `wp-content/plugins/`.
   Alternatively upload `dist/flairlab-v2-rest-compat.zip` in WordPress Admin.
2. Activate **FLAIRLAB V2 REST Compatibility**.
3. Confirm Yoast SEO is active.
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

- No WordPress installation or activation is performed automatically by this repository.
