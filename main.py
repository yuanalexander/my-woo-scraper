import requests
import pandas as pd
import time
import re
import ssl
from datetime import datetime
from bs4 import BeautifulSoup

# --- [系统环境补丁] ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

def clean_html_for_woo(raw_html):
    if not raw_html: return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tags in soup(["script", "style", "iframe", "button", "input", "header", "footer", "nav"]):
        tags.decompose()
    for tag in soup.find_all(True):
        tag.attrs = {}
    cleaned = str(soup).replace('\n', ' ').replace('\r', '').strip()
    return " ".join(cleaned.split())

def get_data(api_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(api_url, headers=headers, timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求失败: {e}")
        return None

# --- [SKU 生成器] ---
class SKUGenerator:
    def __init__(self, start_num):
        self.counter = int(start_num) - 1
    def next_parent_sku(self):
        self.counter += 1
        return f"CW-{self.counter}"

def process_to_woo_format(products, limit, sku_gen):
    extracted = []
    for p in products:
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit: break
        
        parent_sku = sku_gen.next_parent_sku()
        
        image_lookup = {}
        all_imgs_urls = []
        for img in p.get('images', []):
            full_url = re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src'])
            image_lookup[img['id']] = full_url
            all_imgs_urls.append(full_url)
        
        parent_main_img = all_imgs_urls[0] if all_imgs_urls else ""
        images_str = ",".join(all_imgs_urls)
        
        full_desc = clean_html_for_woo(p.get('body_html', ''))
        options = p.get('options', [])
        opt_configs = [{'name': o['name'], 'values': ", ".join(o['values'])} for o in options]
        while len(opt_configs) < 3: opt_configs.append({'name': '', 'values': ''})

        # 父产品行
        extracted.append({
            'Type': 'variable', 'SKU': parent_sku, 'Name': p['title'], 'Published': 1,
            'Description': full_desc, 'In stock?': 1, 'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''), 'Images': images_str, 'Parent': '',
            'Attribute 1 name': opt_configs[0]['name'], 'Attribute 1 value(s)': opt_configs[0]['values'], 'Attribute 1 visible': 1, 'Attribute 1 global': 1,
            'Attribute 2 name': opt_configs[1]['name'], 'Attribute 2 value(s)': opt_configs[1]['values'], 'Attribute 2 visible': 1, 'Attribute 2 global': 1,
            'Attribute 3 name': opt_configs[2]['name'], 'Attribute 3 value(s)': opt_configs[2]['values'], 'Attribute 3 visible': 1, 'Attribute 3 global': 1,
        })

        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
                variant_sku = f"{parent_sku}-{idx}"
                v_image_id = v.get('image_id')
                v_img_url = image_lookup.get(v_image_id, parent_main_img) if v_image_id else parent_main_img
                
                extracted.append({
                    'Type': 'variation', 'SKU': variant_sku, 'Name': f"{p['title']} - {v['title']}",
                    'Published': 1, 'In stock?': 1, 'Regular price': v['price'], 'Images': v_img_url, 'Parent': parent_sku,
                    'Attribute 1 name': opt_configs[0]['name'], 'Attribute 1 value(s)': v.get('option1', '') if opt_configs[0]['name'] else '',
                    'Attribute 2 name': opt_configs[1]['name'], 'Attribute 2 value(s)': v.get('option2', '') if opt_configs[1]['name'] else '',
                    'Attribute 3 name': opt_configs[2]['name'], 'Attribute 3 value(s)': v.get('option3', '') if opt_configs[2]['name'] else '',
                })
    return extracted

def main():
    while True:
        print("\n" + "="*60)
        print("Shopify To WooCommerce v15.0 (文件名 SKU 范围标注版)")
        print("SKU 规则: CW-XXXXXXXX | 自动计算结束编号 | Win10/11 兼容")
        print("="*60)
        
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input: continue

        while True:
            sku_start_input = input("请输入本次起始序号 (如 10000001): ").strip()
            if sku_start_input.isdigit(): break
            print("错误：请输入纯数字！")

        match = re.search(r'https?://([^/]+)', url_input)
        if not match: continue
        base_url = f"https://{match.group(1)}"
        sku_gen = SKUGenerator(sku_start_input)
        all_data = []

        if "/products/" in url_input and ".json" not in url_input:
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and 'product' in data:
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
        else:
            api_path = f"/collections/{url_input.split('/collections/')[1].split('/')[0]}/products.json" if "/collections/" in url_input else "/products.json"
            try:
                max_num = int(input("需要采集多少个父产品? (默认 10): ") or 10)
            except: max_num = 10
            page = 1
            while len([i for i in all_data if i.get('Type') == 'variable']) < max_num:
                data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
                if not data or not data.get('products'): break
                all_data.extend(process_to_woo_format(data['products'], max_num, sku_gen))
                print(f" 已成功处理 {len([i for i in all_data if i.get('Type') == 'variable'])} 个产品...")
                page += 1

        if all_data:
            # --- 新增逻辑：提取起始和结束的父 SKU ---
            parent_skus = [row['SKU'] for row in all_data if row['Type'] == 'variable']
            start_sku = parent_skus[0]
            end_sku = parent_skus[-1]
            timestamp = datetime.now().strftime("%H%M%S") # 仅保留时分秒，缩短文件名长度
            
            # 生成文件名：woo_CW-10000001_to_CW-10000010_143005.csv
            filename = f"woo_{start_sku}_to_{end_sku}_{timestamp}.csv"
            
            pd.DataFrame(all_data).to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n[任务成功]")
            print(f"文件保存为: {filename}")
            print(f"下次采集建议起始序号: {int(end_sku.replace('CW-', '')) + 1}")
        else:
            print("\n[失败] 未能采集到数据。")
        
        choice = input("\n输入 'r' 重新开始，按其他任意键关闭程序: ").lower()
        if choice != 'r': break

if __name__ == "__main__":
    main()
