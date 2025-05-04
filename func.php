add_filter('woocommerce_admin_order_data_after_order_details', 'show_moysklad_uuid_field');
function show_moysklad_uuid_field($order){
    $uuid = get_post_meta($order->get_id(), '_moysklad_uuid', true);
    echo '<p><strong>Moysklad UUID:</strong> ' . esc_html($uuid) . '</p>';
}
