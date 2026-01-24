import requests
import pandas as pd
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup

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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求失败: {e}")
        return None

class SKUGenerator:
    def __init__(self):
        self.counter = 10000000 
    def next_parent_sku(self):
        self.counter += 1
        return f"CW-{self.counter}"

def process_to_woo_format(products, limit, sku_gen):
    extracted = []
    for p in products:
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit:
            break
        
        parent_sku = sku_gen.next_parent_sku()
        all_imgs = [re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src']) for img in p.get('images', [])]
        images_str = ",".join(all_imgs)
        full_desc = clean_html_for_woo(p.get('body_html', ''))

        options = p.get('options', [])
        # 最多支持 3 个属性
        opt_configs = []
        for i in range(3):
            if i < len(options):
                opt_configs.append({
                    'name': options[i]['name'],
                    'values': ", ".join(options[i]['values'])
                })
            else:
                opt_configs.append({'name': '', 'values': ''})

        # --- 1. 父产品行 (variable) ---
        parent_row = {
            'Type': 'variable',
            'SKU': parent_sku,
            'Name': p['title'],
            'Published': 1,
            'Is featured?': 0,
            'Visibility in catalog': 'visible',
            'Description': full_desc,
            'Tax status': 'taxable',
            'In stock?': 1,
            'Backorders allowed?': 0,
            'Sold individually?': 0,
            'Weight (g)': p['variants'][0].get('grams', '') if p['variants'] else '',
            'Allow customer reviews?': 1,
            'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''),
            'Tags': ", ".join(p.get('tags', [])) if isinstance(p.get('tags'), list) else p.get('tags', ''),
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
                v_img = re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', v['featured_image']['src']) if v.get('featured_image') else ""
                
                variant_row = {
                    'Type': 'variation',
                    'SKU': variant_sku,
                    'Name': f"{p['title']} - {v['title']}",
                    'Published': 1,
                    'Description': '', 
                    'In stock?': 1,
                    'Regular price': v['price'],
                    'Images': v_img if v_img else '',
                    'Parent': parent_sku,
                    # 变体行只需填入具体对应的属性值
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
        print("Shopify To WooCommerce 采集器 v11.0 (Schema 对齐版)")
        print("SKU: CW-10000001 | 模式: 官方 CSV 标准映射")
        print("="*50)
        
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input: continue

        match = re.search(r'https?://([^/]+)', url_input)
        if not match:
            print("URL 错误"); continue
            
        base_url = f"https://{match.group(1)}"
        sku_gen = SKUGenerator()
        all_data = []

        if "/products/" in url_input and ".json" not in url_input:
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            print(f"[*] 正在分析单品: {product_handle}")
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and 'product' in data:
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
        else:
            if "/collections/" in url_input:
                c_handle = url_input.split("/collections/")[1].split("/")[0]
                api_path = f"/collections/{c_handle}/products.json"
            else:
                api_path = "/products.json"

            try:
                max_num = int(input("请输入要抓取的父产品数量 (默认 10): ") or 10)
            except:
                max_num = 10

            page = 1
            while len([i for i in all_data if i.get('Type') == 'variable']) < max_num:
                data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
                if not data or not data.get('products'): break
                batch = process_to_woo_format(data['products'], max_num, sku_gen)
                all_data.extend(batch)
                print(f" 已采集 {len([i for i in all_data if i.get('Type') == 'variable'])} 个产品...")
                page += 1

        if all_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"woo_standard_{timestamp}.csv"
            pd.DataFrame(all_data).to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n[成功] 文件已生成: {filename}\n请在 WooCommerce 导入时直接上传。")
        else:
            print("\n[错误] 未能获取数据。")

        choice = input("\n输入 'r' 重新开始，按其他任意键退出: ").lower()
        if choice != 'r': break

if __name__ == "__main__":
    main()
