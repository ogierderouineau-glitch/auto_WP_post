# Speech2Post Dynamic Shortcodes

This small WordPress plugin exposes Python-generated native post metadata
through one generic shortcode. It does not create or read ACF output fields.

The plugin is optional. When it is not installed, the publishing pipeline
omits `_generated_variables` and continues publishing the remaining WordPress,
Yoast, and ACF fields normally. Clients without the plugin should leave
`post shortcode variables` empty and avoid placing `[post_variable]` in their
templates, because WordPress cannot replace an unregistered shortcode.

## Install

1. Copy `speech2post-dynamic-shortcodes` to `wp-content/plugins/`.
2. Activate **Speech2Post Dynamic Shortcodes** in WordPress.

Deactivate the former FLAIRLAB-branded plugin before activating this
replacement. A deactivated copy does not execute and can remain installed
until it can be deleted through WordPress Admin or the hosting filesystem.

## Usage

Python sends one REST-visible meta object:

```json
{
  "meta": {
    "_generated_variables": {
      "staff_name": "Anna Schmidt"
    }
  }
}
```

The post can reuse that value:

```text
[post_variable name="staff_name"]
```

An optional fallback is shown when the field is empty:

```text
[post_variable name="staff_name" default="our bartender"]
```

The variable name is the selected `ACF_fields_schema.field_key` from the
workbook's `post_types.post shortcode variables` column. Values are sanitized
when saved and HTML-escaped when rendered.

## WordPress limitation

Shortcodes work in content areas that run WordPress's `do_shortcode` filter,
including the Gutenberg Shortcode block. They do not run in the post title,
URL slug, SEO fields, or arbitrary theme/ACF settings unless that field or
theme explicitly processes shortcodes.
