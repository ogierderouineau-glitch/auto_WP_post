<?php
/**
 * Plugin Name: Speech2Post REST Compatibility
 * Description: Exposes the V2 workbook Yoast/Open Graph destinations and read-only Yoast SEO data through WordPress REST.
 * Version: 0.2.0
 * Author: Speech2Post
 */

defined('ABSPATH') || exit;

/**
 * Register workbook-facing Open Graph names and Yoast's native meta keys.
 */
function speech2post_register_yoast_rest_meta(): void {
    $keys = [
        'yoast_wpseo_opengraph_title',
        'yoast_wpseo_opengraph_description',
        '_yoast_wpseo_opengraph-title',
        '_yoast_wpseo_opengraph-description',
    ];

    foreach ($keys as $key) {
        register_post_meta('post', $key, [
            'type' => 'string',
            'single' => true,
            'show_in_rest' => true,
            'sanitize_callback' => 'sanitize_text_field',
            'auth_callback' => static function (): bool {
                return current_user_can('edit_posts');
            },
        ]);
    }
}
add_action('init', 'speech2post_register_yoast_rest_meta');

/**
 * Expose Yoast SEO data for every REST-enabled post type so the app can scan
 * existing keyphrases. The app only reads these keys. Add future keys here.
 */
function speech2post_register_yoast_seo_scan_meta(): void {
    $keys = [
        '_yoast_wpseo_focuskw',
        '_yoast_wpseo_keywordsynonyms',
        '_yoast_wpseo_focuskeywords',
        '_yoast_wpseo_title',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_linkdex',
        '_yoast_wpseo_content_score',
        '_yoast_wpseo_is_cornerstone',
        '_yoast_wpseo_canonical',
        '_yoast_wpseo_meta-robots-noindex',
        '_yoast_wpseo_primary_category',
        '_yoast_wpseo_twitter-title',
        '_yoast_wpseo_twitter-description',
        '_yoast_wpseo_opengraph-image',
        '_yoast_wpseo_bctitle',
    ];

    foreach (get_post_types(['show_in_rest' => true], 'names') as $post_type) {
        foreach ($keys as $key) {
            register_post_meta($post_type, $key, [
                'type' => 'string',
                'single' => true,
                'show_in_rest' => true,
                'auth_callback' => static function (): bool {
                    return current_user_can('edit_posts');
                },
            ]);
        }
    }
}
add_action('init', 'speech2post_register_yoast_seo_scan_meta', 20);

/**
 * Synchronize workbook-friendly REST keys to Yoast's native Open Graph keys.
 */
function speech2post_sync_yoast_open_graph_meta(
    int $meta_id,
    int $post_id,
    string $meta_key,
    mixed $meta_value
): void {
    $mapping = [
        'yoast_wpseo_opengraph_title' => '_yoast_wpseo_opengraph-title',
        'yoast_wpseo_opengraph_description' => '_yoast_wpseo_opengraph-description',
    ];

    if (!isset($mapping[$meta_key])) {
        return;
    }

    $native_key = $mapping[$meta_key];
    $value = sanitize_text_field((string) $meta_value);
    if (get_post_meta($post_id, $native_key, true) !== $value) {
        update_post_meta($post_id, $native_key, $value);
    }
}
add_action('added_post_meta', 'speech2post_sync_yoast_open_graph_meta', 10, 4);
add_action('updated_post_meta', 'speech2post_sync_yoast_open_graph_meta', 10, 4);
