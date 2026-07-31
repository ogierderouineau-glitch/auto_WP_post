# Speech2Post REST Compatibility

This WordPress plugin resolves staging Yoast/Open Graph REST compatibility
without weakening the workbook contract:

- exposes `yoast_wpseo_opengraph_title` through REST;
- exposes `yoast_wpseo_opengraph_description` through REST;
- synchronizes the friendly REST keys to Yoast native Open Graph meta keys.

## Install on staging

1. Copy `speech2post-rest-compat` into `wp-content/plugins/`.
   Alternatively upload `dist/speech2post-rest-compat.zip` in WordPress Admin.
2. Activate **Speech2Post REST Compatibility**.
3. Confirm Yoast SEO is active.
4. Run the read-only preflight:

If the former FLAIRLAB-branded plugin is installed, deactivate it before
activating this replacement. A deactivated copy can remain installed safely;
delete it later through WordPress Admin, WP-CLI, SFTP, or the hosting file
manager when access permits.

```bash
.venv/bin/python tools/wordpress_preflight.py \
  data/knowledge/{client_id}.xlsm \
  --output data/audits/v2_wordpress_staging_preflight.json
```

The report must return `"ready": true` before V2 publication is enabled.

After the package has been uploaded, activation can also be done through the
authenticated REST API:

```bash
.venv/bin/python tools/activate_wordpress_plugin.py --activate
```

Running the command without `--activate` is read-only.

## Notes

- No WordPress installation or activation is performed automatically by this repository.
