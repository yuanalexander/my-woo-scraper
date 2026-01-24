import requests
import pandas as pd
import time
import re
import ssl
from datetime import datetime
from bs4 import BeautifulSoup

# 针对旧版 Windows 的网络安全补丁
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
    # 模拟最新版 Edge 浏览器，确保 Win10/11 访问流畅
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edge/120.0.0.0'}
    try:
        response = requests.get(api_url, headers=headers, timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求失败: {e}")
        return None

class SKUGenerator:
    def __init__(self):
        # 严格执行: SKU 从 CW-10000001 开始递增
        self.counter = 10000000 
    def next_parent_sku(self):
        self.counter += 1
        return f"CW-{self.counter}"

def process_to_woo_format(products, limit, sku_gen):
    extracted = []
    for p in products:
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit: break
        
        parent_sku = sku_gen.next_parent_sku()
        all_imgs = [re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src']) for img in p.get('images', [])]
        images_str = ",".join(all_imgs)
        full_desc = clean_html_for_woo(p.get('body_html', ''))

        options = p.get('options', [])
        opt_configs = []
        for i in range(3):
            if i < len(options):
                opt_configs.append({'name': options[i]['name'], 'values': ", ".join(options[i]['values'])})
            else:
                opt_configs.append({'name': '', 'values': ''})

        # 父产品 (variable)
        parent_row = {
            'Type': 'variable',
            'SKU': parent_sku,
            'Name': p['title'],
            'Published': 1,
            'Description': full_desc,
            'In stock?': 1,
            'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''),
            'Images': images_str,
            'Attribute 1 name': opt_configs[0]['name'],
            'Attribute 1 value(s)': opt_configs[0]['values'],
            'Attribute 1 visible': 1,
            'Attribute 1 global': 1,
            'Attribute 2 name': opt_configs[1]['name'],
            'Attribute 2 value(s)': opt_configs[1]['values'],
            'Attribute 2 visible': 1,
            'Attribute 2 global': 1,
            'Attribute 3 name': opt_configs[2]['name'],
            'Attribute 3 value(s)': opt_configs[2]['values'],
            'Attribute 3 visible': 1,
            'Attribute 3 global': 1,
        }
        extracted.append(parent_row)

        # 子变体 (variation)
        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
                # 子 SKU 在父级基础上加后缀
                variant_sku = f"{parent_sku}-{idx}"
                v_img = re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', v['featured_image']['src']) if v.get('featured_image') else ""
                
                variant_row = {
                    'Type': 'variation',
                    'SKU': variant_sku,
                    'Name': f"{p['title']} - {v['title']}",
                    'Published': 1,
                    'In stock?': 1,
                    'Regular price': v['price'],
                    'Images': v_img if v_img else '',
                    'Parent': parent_sku,
                    'Attribute 1 name': opt_configs[0]['name'],
                    'Attribute 1 value(s)': v.get('option1', '') if opt_configs[0]['name'] else '',
                    'Attribute 2 name': opt_configs[1]['name'],
                    'Attribute 2 value(s)': v.get('option2', '') if opt_configs[1]['name'] else '',
                    'Attribute 3 name': opt_configs[2]['name'],
                    'Attribute 3 value(s)': v.get('option3', '') if opt_configs[2]['name'] else '',
                }
                extracted.append(variant_row)
    return extracted

def main():
    while True:
        print("\n" + "="*50)
        print("Shopify To WooCommerce v11.5 (Win10/11 兼容版)")
        print("="*50)
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input: continue
        match = re.search(r'https?://([^/]+)', url_input)
        if not match: continue
        base_url = f"https://{match.group(1)}"
        sku_gen = SKUGenerator()
        all_data = []

        if "/products/" in url_input and ".json" not in url_input:
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and 'product' in data:
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
        else:
            api_path = f"/collections/{url_input.split('/collections/')[1].split('/')[0]}/products.json" if "/collections/" in url_input else "/products.json"
            try:
                max_num = int(input("抓取父产品数量 (默认 10): ") or 10)
            except: max_num = 10
            page = 1
            while len([i for i in all_data if i.get('Type') == 'variable']) < max_num:
                data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
                if not data or not data.get('products'): break
                all_data.extend(process_to_woo_format(data['products'], max_num, sku_gen))
                page += 1

        if all_data:
            filename = f"woo_ready_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            pd.DataFrame(all_data).to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n[成功] 文件已生成: {filename}")
        
        choice = input("\n输入 'r' 重新开始，其他键退出: ").lower()
        if choice != 'r': break

if __name__ == "__main__":
    main()
