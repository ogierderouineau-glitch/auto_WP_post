<?php
/**
 * Plugin Name: Speech2Post Dynamic Shortcodes
 * Description: Exposes generated post-meta variables through a generic shortcode.
 * Version: 0.2.0
 * Author: Speech2Post
 */

defined('ABSPATH') || exit;

function speech2post_sanitize_generated_variables($value): array {
    if (!is_array($value)) {
        return [];
    }

    $sanitized = [];
    foreach ($value as $key => $item) {
        $key = sanitize_key((string) $key);
        if ($key !== '' && is_scalar($item)) {
            $sanitized[$key] = sanitize_text_field((string) $item);
        }
    }

    return $sanitized;
}

/**
 * Register the single generated-variable object for REST-enabled post types.
 */
function speech2post_register_generated_variables_meta(): void {
    $post_types = get_post_types(['show_in_rest' => true], 'names');
    $post_types = apply_filters(
        'speech2post_generated_variable_post_types',
        $post_types
    );

    foreach (array_unique((array) $post_types) as $post_type) {
        register_post_meta(
            (string) $post_type,
            '_generated_variables',
            [
                'type' => 'object',
                'single' => true,
                'show_in_rest' => [
                    'schema' => [
                        'type' => 'object',
                        'additionalProperties' => [
                            'type' => 'string',
                        ],
                    ],
                ],
                'sanitize_callback' => 'speech2post_sanitize_generated_variables',
                'auth_callback' => static function (
                    bool $allowed,
                    string $meta_key,
                    int $post_id
                ): bool {
                    return current_user_can('edit_post', $post_id);
                },
            ]
        );
    }
}
add_action('init', 'speech2post_register_generated_variables_meta', 100);

/**
 * Return one display-safe generated variable from the current post.
 *
 * Example: [post_variable name="staff_name" default="our bartender"]
 */
function speech2post_post_variable_shortcode($attributes = []): string {
    $attributes = is_array($attributes) ? $attributes : [];
    $attributes = shortcode_atts(
        [
            'name' => '',
            'default' => '',
        ],
        $attributes,
        'post_variable'
    );

    $post_id = get_the_ID();
    $key = sanitize_key((string) $attributes['name']);
    $fallback = (string) $attributes['default'];

    if (!$post_id || !$key) {
        return esc_html($fallback);
    }

    $variables = get_post_meta($post_id, '_generated_variables', true);
    $value = is_array($variables) ? ($variables[$key] ?? '') : '';

    if (!is_scalar($value) || trim((string) $value) === '') {
        return esc_html($fallback);
    }

    return esc_html((string) $value);
}
add_shortcode('post_variable', 'speech2post_post_variable_shortcode');
