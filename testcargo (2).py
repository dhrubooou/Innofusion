import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import torch
import torch.nn as nn
import torch.optim as optim
import productorder

class RankingModel(nn.Module):
    def __init__(self, input_size, hidden_size):
        super(RankingModel, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, 1)
    
    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = self.fc2(x)
        return x

def simulate_cargo_shipping(product_name, order_date, is_quick_order=False):
    if is_quick_order:
        delivery_time_mean = 48  # Around 2 days for quick orders
        delivery_time_std = 12
    else:
        delivery_time_mean = 120  # Around 5 days for normal orders
        delivery_time_std = 24
    
    delivery_time = max(1, int(np.random.normal(delivery_time_mean, delivery_time_std)))
    delivery_dates = [order_date + timedelta(hours=i) for i in range(delivery_time)]

    data = []
    delivered = False
    for timestamp in delivery_dates:
        status = 'Delivered' if timestamp >= delivery_dates[-1] else 'In Transit'
        data.append({
            'Timestamp': timestamp,
            'Status': status,
            'Order Type': 'Quick Order' if is_quick_order else 'Normal Order'
        })
        if status == 'Delivered':
            delivered = True

    tracking_df = pd.DataFrame(data)
    return tracking_df

def process_quick_order(product_name, shop, order_date, order_quantity):
    print(f"Processing quick order for {product_name} in {shop}")
    quick_order_quantity = int(input(f"Enter quick order quantity for {shop} (max {order_quantity}): "))
    
    if quick_order_quantity > 0 and quick_order_quantity <= order_quantity:
        normal_order_quantity = order_quantity - quick_order_quantity
        
        # Process quick order
        print(f"Quick order for {product_name} in {shop} on {order_date} for {quick_order_quantity} units")
        quick_tracking_df = simulate_cargo_shipping(product_name, order_date, is_quick_order=True)
        print("Quick Order Tracking:")
        print(quick_tracking_df)
        
        # Process normal order if there's remaining quantity
        if normal_order_quantity > 0:
            print(f"Normal order for {product_name} in {shop} on {order_date} for {normal_order_quantity} units")
            normal_tracking_df = simulate_cargo_shipping(product_name, order_date, is_quick_order=False)
            print("Normal Order Tracking:")
            print(normal_tracking_df)
            
            # Combine quick and normal order tracking data
            tracking_df = pd.concat([quick_tracking_df, normal_tracking_df], ignore_index=True)
        else:
            tracking_df = quick_tracking_df
    else:
        print("Invalid quick order quantity. Processing as normal order.")
        tracking_df = simulate_cargo_shipping(product_name, order_date, is_quick_order=False)
        print("Normal Order Tracking:")
        print(tracking_df)
    
    return tracking_df

def rename_shop(shop_id):
    shop_mapping = {'shop1': 'Shop_B', 'shop2': 'Shop_C', 'shop3': 'Shop_A'}
    return shop_mapping.get(shop_id, shop_id)

def parse_order_date(order_date):
    print(f"Debug: Parsing order date: {order_date}")
    if pd.isna(order_date):
        print("Debug: Order date is NaT")
        return None
    if isinstance(order_date, str):
        try:
            parsed_date = pd.to_datetime(order_date)
            print(f"Debug: Parsed string date to: {parsed_date}")
            return parsed_date
        except Exception as e:
            print(f"Debug: Failed to parse string date: {e}")
            return None
    parsed_date = pd.to_datetime(order_date, errors='coerce')
    print(f"Debug: Coerced date to: {parsed_date}")
    return parsed_date

def rank_stores(sales_data_file, reviews_data_file):
    try:
        sales_data = pd.read_csv(sales_data_file)
        reviews_data = pd.read_csv(reviews_data_file)
    except Exception as e:
        print(f"Error reading CSV files: {e}")
        return []

    sales_data['Shop_ID'] = sales_data['Shop_ID'].str.replace(' ', '_')
    reviews_data['Shop_ID'] = reviews_data['Shop_ID'].str.replace(' ', '_')

    merged_data = pd.merge(sales_data, reviews_data, on='Shop_ID')

    if merged_data.empty:
        raise ValueError("The merged DataFrame is empty. Please check the input CSV files for consistency.")

    x = pd.get_dummies(merged_data.drop(['Shop_ID', 'Month', 'Total_Sales_Amount', 'Review Text', 'Review ID'], axis=1))
    y = merged_data['Total_Sales_Amount']

    input_size = x.shape[1]
    hidden_size = 64

    model = RankingModel(input_size, hidden_size)
    try:
        model.load_state_dict(torch.load('ranking_model.pth'))
    except Exception as e:
        print(f"Error loading model state: {e}")
        return []

    features = x.values
    features_tensor = torch.tensor(features, dtype=torch.float32)

    model.eval()
    with torch.no_grad():
        predicted_sales = model(features_tensor)

    predicted_sales = predicted_sales.squeeze().tolist()
    stores = merged_data['Shop_ID'].tolist()
    store_sales_dict = dict(zip(stores, predicted_sales))

    ranked_stores = sorted(store_sales_dict.items(), key=lambda x: x[1], reverse=True)

    return ranked_stores

def save_demand_data(demand_data, filename="demand_data.csv"):
    demand_data.to_csv(filename, index=False)
    print(f"Demand data saved to {filename}")

def cargo_tracking_main():
    product_name_input = input("Enter the product name: ")
    productorder.take_orders(product_name_input)
    orders_df = productorder.load_orders()
    print("Debug: Raw loaded orders:")
    print(orders_df)

    orders_df['Shop'] = orders_df['Shop'].apply(rename_shop)
    print("Debug: Orders after renaming shops:")
    print(orders_df)

    ranked_stores = rank_stores('shop_sale.csv', 'shop_reviews.csv')

    ranked_stores = [(rename_shop(store), score) for store, score in ranked_stores]
    print("Ranking of stores:")
    for rank, (store, _) in enumerate(ranked_stores, start=1):
        print(f"{rank}. {store}")

    product_orders = orders_df[orders_df['Product Name'] == product_name_input]
    product_orders = product_orders[pd.notna(product_orders['Order Date']) & (product_orders['Order Quantity'] > 0)]
    print(f"Debug: Valid orders for {product_name_input}:")
    print(product_orders)

    if product_orders.empty:
        print(f"No valid orders placed for {product_name_input}.")
        return

    quick_order_enabled = input("Do you want to enable quick orders? (yes/no): ").lower() == 'yes'

    # Aggregate orders by shop
    aggregated_orders = product_orders.groupby('Shop').agg({
        'Order Date': 'first',
        'Order Quantity': 'sum'
    }).reset_index()

    tracking_data = []

    for _, order in aggregated_orders.iterrows():
        shop = order['Shop']
        order_date = parse_order_date(order['Order Date'])
        order_quantity = int(order['Order Quantity'])
        print(f"Debug: Processing aggregated order - Shop: {shop}, Order Date: {order_date}, Total Quantity: {order_quantity}")
        
        if pd.notna(order_date):
            if quick_order_enabled:
                tracking_df = process_quick_order(product_name_input, shop, order_date, order_quantity)
            else:
                print(f"Normal order for {product_name_input} in {shop} on {order_date} for {order_quantity} units")
                tracking_df = simulate_cargo_shipping(product_name_input, order_date, is_quick_order=False)
                print(tracking_df)
            
            tracking_data.append(tracking_df)
        else:
            print(f"Invalid or missing order date for {product_name_input} in {shop}")

    if tracking_data:
        all_tracking_data = pd.concat(tracking_data, ignore_index=True)
        save_demand_data(all_tracking_data)

if __name__ == "__main__":
    cargo_tracking_main()
