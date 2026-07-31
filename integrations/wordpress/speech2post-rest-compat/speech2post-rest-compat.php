<?php
/**
 * Plugin Name: Speech2Post REST Compatibility
 * Description: Exposes the V2 workbook Yoast/Open Graph destinations through WordPress REST.
 * Version: 0.1.0
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
