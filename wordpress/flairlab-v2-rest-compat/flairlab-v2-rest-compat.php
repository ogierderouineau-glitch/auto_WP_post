<?php
/**
 * Plugin Name: FLAIRLAB V2 REST Compatibility
 * Description: Exposes the V2 workbook ACF and Yoast/Open Graph destinations through WordPress REST.
 * Version: 0.1.0
 * Author: FLAIRLAB
 */

defined('ABSPATH') || exit;

const FLAIRLAB_V2_RELATED_LINKS_FIELD_KEY = 'field_flairlab_v2_related_links_html';

/**
 * Add the missing ACF field to Event posts when ACF Pro is available.
 *
 * The field name is the workbook destination. It deliberately does not reuse
 * gallery_html because those fields have different semantics.
 */
function flairlab_v2_register_acf_fields(): void {
    if (!function_exists('acf_add_local_field_group')) {
        return;
    }

    acf_add_local_field_group([
        'key' => 'group_flairlab_v2_rest_contract',
        'title' => 'FLAIRLAB V2 REST Contract',
        'fields' => [
            [
                'key' => FLAIRLAB_V2_RELATED_LINKS_FIELD_KEY,
                'label' => 'Related Links HTML',
                'name' => 'related_links_html',
                'type' => 'textarea',
                'instructions' => 'Deterministically generated internal links from the V2 pipeline.',
                'required' => 0,
                'new_lines' => '',
            ],
        ],
        'location' => [
            [
                [
                    'param' => 'post_type',
                    'operator' => '==',
                    'value' => 'post',
                ],
            ],
        ],
        'show_in_rest' => 1,
        'active' => true,
    ]);
}
add_action('acf/init', 'flairlab_v2_register_acf_fields');

/**
 * Register workbook-facing Open Graph names and Yoast's native meta keys.
 */
function flairlab_v2_register_yoast_rest_meta(): void {
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
add_action('init', 'flairlab_v2_register_yoast_rest_meta');

/**
 * Synchronize workbook-friendly REST keys to Yoast's native Open Graph keys.
 */
function flairlab_v2_sync_yoast_open_graph_meta(
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
add_action('added_post_meta', 'flairlab_v2_sync_yoast_open_graph_meta', 10, 4);
add_action('updated_post_meta', 'flairlab_v2_sync_yoast_open_graph_meta', 10, 4);

