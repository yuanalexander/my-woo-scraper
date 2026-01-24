import requests
import pandas as pd
import time
import re
from bs4 import BeautifulSoup

def clean_html_for_woo(raw_html):
    """
    深度清洗 HTML：
    1. 移除 script, style, iframe 等危险标签
    2. 移除所有标签的 style, class, id 等内联属性，防止样式污染
    3. 保留 p, br, strong, ul, li 等基础结构标签
    """
    if not raw_html:
        return ""
    # 使用 html.parser 兼容性最好
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # 彻底移除这些不安全的标签
    for tags in soup(["script", "style", "iframe", "button", "input", "header", "footer", "nav"]):
        tags.decompose()
        
    # 清洗所有剩余标签的属性
    for tag in soup.find_all(True):
        tag.attrs = {}
        
    # 将清洗后的 soup 转回字符串，并压缩多余空白
    cleaned = str(soup).replace('\n', ' ').replace('\r', '').strip()
    return " ".join(cleaned.split())

def get_data(api_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"网络连接失败: {e}")
        return None

class SKUGenerator:
    def __init__(self):
        # 严格执行: 从 CW-10000001 开始递增
        self.counter = 10000000 
    def next_parent_sku(self):
        self.counter += 1
        return f"CW-{self.counter}"

sku_gen = SKUGenerator()

def process_to_woo_format(products, limit):
    extracted = []
    for p in products:
        # 统计父产品数量
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit:
            break
        
        parent_sku = sku_gen.next_parent_sku()
        
        # 高清大图处理
        all_imgs = []
        for img in p.get('images', []):
            src = img['src']
            # 去除 Shopify 缩略图尺寸后缀，获取原图
            big_img = re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', src)
            all_imgs.append(big_img)
        images_str = ",".join(all_imgs)

        # 清洗描述文字
        full_desc = clean_html_for_woo(p.get('body_html', ''))

        # 1. 创建 WooCommerce Variable (父产品行)
        parent_row = {
            'Type': 'variable',
            'SKU': parent_sku,
            'Name': p['title'],
            'Published': 1,
            'Is featured?': 0,
            'Visibility in catalog': 'visible',
            'Description': full_desc,
            'In stock?': 1,
            'Stock': '',
            'Weight (g)': p['variants'][0].get('grams', '') if p['variants'] else '',
            'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''),
            'Tags': ", ".join(p.get('tags', [])) if isinstance(p.get('tags'), list) else p.get('tags', ''),
            'Images': images_str,
            'Parent': '', # 父产品此处为空
            'Attribute 1 name': p['options'][0]['name'] if len(p.get('options', [])) > 0 else '',
            'Attribute 1 value(s)': ", ".join(p['options'][0]['values']) if len(p.get('options', [])) > 0 else '',
            'Attribute 1 visible': 1,
            'Attribute 1 global': 1,
        }
        extracted.append(parent_row)

        # 2. 创建 WooCommerce Variation (子变体行)
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
                    'Parent': parent_sku, # 通过 SKU 关联
                    'Attribute 1 name': p['options'][0]['name'] if len(p.get('options', [])) > 0 else '',
                    'Attribute 1 value(s)': v.get('option1', ''),
                }
                extracted.append(variant_row)
            
    return extracted

# --- 主程序 ---
print("--- Win10 专用: Shopify 转 WooCommerce 采集器 v7.0 ---")
print("SKU 起始: CW-10000001 | 模式: 深度 HTML 清洗")

url_input = input("请输入目标 URL: ").strip()
try:
    max_num = int(input("需要爬取多少个父产品? (默认 10): ") or 10)
except:
    max_num = 10

# 智能识别域名
match = re.search(r'https?://([^/]+)', url_input)
if not match:
    print("域名格式错误，请包含 http:// 或 https://"); exit()
base_url = f"https://{match.group(1)}"

all_data = []

# 执行分页爬取
page = 1
while len([i for i in all_data if i.get('Type') == 'variable']) < max_num:
    # 自动识别是分类还是全店
    api_path = "/products.json"
    if "/collections/" in url_input:
        c_handle = url_input.split("/collections/")[1].split("/")[0].split("?")[0]
        api_path = f"/collections/{c_handle}/products.json"
    
    data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
    if not data or not data.get('products'):
        break
        
    batch = process_to_woo_format(data['products'], max_num)
    all_data.extend(batch)
    page += 1

if all_data:
    # 转换为 CSV 并保存
    df = pd.DataFrame(all_data)
    filename = "woo_ready_import.csv"
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"\n[成功] 已生成 Win10 兼容 CSV 文件: {filename}")
    print(f"第一个 SKU: {all_data[0]['SKU']}")
else:
    print("\n[失败] 未能抓取到数据，请确认该站点是否为 Shopify 架构。")

input("\n按回车键关闭窗口...")
