import requests
import pandas as pd
import time
import re
import ssl
from datetime import datetime
from bs4 import BeautifulSoup

# 针对 Windows 环境的 SSL 补丁
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

class SKUGenerator:
    def __init__(self):
        # 严格执行: 从 CW-10000001 开始递增
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
        
        # 提取并清洗父级大图
        all_imgs = [re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src']) for img in p.get('images', [])]
        images_str = ",".join(all_imgs)
        # 获取父级主图作为备份
        parent_main_img = all_imgs[0] if all_imgs else ""
        
        full_desc = clean_html_for_woo(p.get('body_html', ''))

        options = p.get('options', [])
        opt_configs = []
        for i in range(3):
            if i < len(options):
                opt_configs.append({'name': options[i]['name'], 'values': ", ".join(options[i]['values'])})
            else:
                opt_configs.append({'name': '', 'values': ''})

        # --- 1. 父产品行 (variable) ---
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
            'Parent': '',
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

        # --- 2. 子变体行 (variation) ---
        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
                variant_sku = f"{parent_sku}-{idx}"
                
                # 变体图逻辑：优先用变体图，没有则用父级主图
                v_img = ""
                if v.get('featured_image'):
                    v_img = re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', v['featured_image']['src'])
                else:
                    v_img = parent_main_img # 自动补充缺失的变体图
                
                variant_row = {
                    'Type': 'variation',
                    'SKU': variant_sku,
                    'Name': f"{p['title']} - {v['title']}",
                    'Published': 1,
                    'In stock?': 1,
                    'Regular price': v['price'],
                    'Images': v_img, # 确保变体一定有图
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
        print("Shopify To WooCommerce v12.0 (图片补全版)")
        print("系统支持: Win10 / Win11")
        print("="*50)
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input: continue
        match = re.search(r'https?://([^/]+)', url_input)
        if not match: continue
        base_url = f"https://{match.group(1)}"
        sku_gen = SKUGenerator()
        all_data = []

        # 逻辑判断：单品 vs 分类
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
            filename = f"woo_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            pd.DataFrame(all_data).to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n[成功] 文件已生成: {filename}")
        
        choice = input("\n输入 'r' 重新开始，其他键退出: ").lower()
        if choice != 'r': break

if __name__ == "__main__":
    main()
