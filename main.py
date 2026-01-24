import requests
import pandas as pd
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup

# --- [工具函数：HTML 清洗] ---
def clean_html_for_woo(raw_html):
    if not raw_html: return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tags in soup(["script", "style", "iframe", "button", "input", "header", "footer", "nav"]):
        tags.decompose()
    for tag in soup.find_all(True):
        tag.attrs = {}
    cleaned = str(soup).replace('\n', ' ').replace('\r', '').strip()
    return " ".join(cleaned.split())

# --- [工具函数：网络请求] ---
def get_data(api_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"网络连接失败: {e}")
        return None

# --- [SKU 生成器：按照 CW-10000001 规则] ---
class SKUGenerator:
    def __init__(self):
        # 始终从 10000001 开始
        self.counter = 10000000 
    def next_parent_sku(self):
        self.counter += 1
        return f"CW-{self.counter}"

# --- [核心处理：转为 WooCommerce 格式] ---
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

        # 父产品行 (Variable)
        parent_row = {
            'Type': 'variable',
            'SKU': parent_sku,
            'Name': p['title'],
            'Published': 1,
            'Description': full_desc,
            'In stock?': 1,
            'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''),
            'Tags': ", ".join(p.get('tags', [])) if isinstance(p.get('tags'), list) else p.get('tags', ''),
            'Images': images_str,
            'Parent': '',
            'Attribute 1 name': p['options'][0]['name'] if len(p.get('options', [])) > 0 else '',
            'Attribute 1 value(s)': ", ".join(p['options'][0]['values']) if len(p.get('options', [])) > 0 else '',
            'Attribute 1 visible': 1,
            'Attribute 1 global': 1,
        }
        extracted.append(parent_row)

        # 子变体行 (Variation)
        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
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
                    'Attribute 1 name': p['options'][0]['name'] if len(p.get('options', [])) > 0 else '',
                    'Attribute 1 value(s)': v.get('option1', ''),
                }
                extracted.append(variant_row)
    return extracted

# --- [主程序] ---
def main():
    while True:
        print("\n" + "="*50)
        print("Shopify To WooCommerce 采集器 v9.0")
        print("功能：自动识别单品/分类 | SKU CW-10000001 | 自动时间戳文件名")
        print("="*50)
        
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input: continue

        match = re.search(r'https?://([^/]+)', url_input)
        if not match:
            print("URL 格式无效，请包含 http:// 或 https://"); continue
            
        base_url = f"https://{match.group(1)}"
        sku_gen = SKUGenerator()
        all_data = []

        # 逻辑：单品、分类、全店
        if "/products/" in url_input and ".json" not in url_input:
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            print(f"[*] 正在分析单品: {product_handle}")
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and 'product' in data:
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
            else:
                print("[!] 单品数据抓取失败。")
        
        else:
            if "/collections/" in url_input:
                c_handle = url_input.split("/collections/")[1].split("/")[0]
                print(f"[*] 正在分析分类: {c_handle}")
                api_path = f"/collections/{c_handle}/products.json"
            else:
                print("[*] 正在进行全店采集...")
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

        # --- 生成带时间戳的文件名 ---
        if all_data:
            # 获取当前时间，格式：20240520_143005
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"woo_import_{timestamp}.csv"
            
            df = pd.DataFrame(all_data)
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n[成功] 数据已保存至: {filename}")
        else:
            print("\n[错误] 未抓取到有效数据。")

        # 保持窗口开启
        choice = input("\n输入 'r' 重新采集，按其他任意键退出: ").lower()
        if choice != 'r':
            break

if __name__ == "__main__":
    main()
