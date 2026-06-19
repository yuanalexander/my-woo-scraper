import requests
import pandas as pd
import time
import re
import ssl
from datetime import datetime
from bs4 import BeautifulSoup

VERSION = "17.0"

# --- [系统环境补丁] ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# ─── WooCommerce CSV 29 列（与你现有格式完全一致）───
CSV_COLUMNS = [
    "ID", "Type", "SKU", "Name", "Published", "Is featured?",
    "Visibility in catalog", "Short description", "Description",
    "Regular price", "Sale price", "In stock?", "Stock",
    "Categories", "Tags", "Images", "Parent",
    "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 visible",
    "Attribute 1 global", "Attribute 1 default",
    "Attribute 2 name", "Attribute 2 value(s)", "Attribute 2 visible",
    "Attribute 2 global",
    "Meta: _rank_math_title", "Meta: _rank_math_description",
    "Meta: _rank_math_focus_keyword",
]


def clean_price(price_str):
    """去掉 $ 符号，返回纯数字字符串。"""
    if not price_str:
        return ""
    return str(price_str).replace("$", "").replace(",", "").strip()


def extract_short_desc(html_body, max_chars=200):
    """从 body_html 提取纯文本第一段作为 Short description。"""
    if not html_body:
        return ""
    soup = BeautifulSoup(html_body, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = " ".join(text.split())  # 压缩空白
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "..."


def clean_html_for_woo(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tags in soup(["script", "style", "iframe", "button", "input", "header", "footer", "nav"]):
        tags.decompose()
    for tag in soup.find_all(True):
        tag.attrs = {}
    cleaned = str(soup).replace('\n', ' ').replace('\r', '').strip()
    return " ".join(cleaned.split())


def get_data(api_url, max_retries=3):
    """带重试的 API 请求。遇到 429 限流或临时网络错误自动退避重试。"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(api_url, headers=headers, timeout=30)
            if response.status_code == 429:
                wait = 5 * attempt
                print(f"  ⚠️ 被限流(429)，等待 {wait} 秒后重试 (第{attempt}/{max_retries}次)...")
                time.sleep(wait)
                continue
            if response.status_code == 430:
                print(f"  ⚠️ Shopify 安全拦截(430)，该站点可能屏蔽了 API 访问。")
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                print(f"  ⚠️ 请求超时，重试中 (第{attempt}/{max_retries}次)...")
                time.sleep(3)
            else:
                print(f"  ❌ 请求超时，已重试{max_retries}次仍失败。")
                return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"  ⚠️ 网络错误: {e}，{wait}秒后重试 (第{attempt}/{max_retries}次)...")
                time.sleep(wait)
            else:
                print(f"  ❌ 请求最终失败: {e}")
                return None
    return None


class SKUGenerator:
    """可自定义 SKU 编码规则。"""

    def __init__(self, prefix="CW", start_num=1):
        self.prefix = str(prefix).strip()
        if not self.prefix:
            self.prefix = "CW"
        self.counter = int(start_num) - 1

    @property
    def current_number(self):
        return self.counter

    def next_parent_sku(self):
        self.counter += 1
        return f"{self.prefix}-{self.counter}"

    def variant_sku(self, parent_num, variant_index):
        return f"{self.prefix}-{parent_num}-{variant_index}"

    def suggest_next_start(self):
        return self.counter + 1

    def describe(self):
        return f"前缀: {self.prefix}  |  父SKU: {self.prefix}-XXXX  |  变体: {self.prefix}-XXXX-N"


def process_to_woo_format(products, limit, sku_gen):
    """将 Shopify 产品数据转为 29 列 WooCommerce CSV 行。"""
    extracted = []
    for p in products:
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit:
            break

        parent_sku = sku_gen.next_parent_sku()
        parent_num = sku_gen.current_number

        # ── 图片 ──
        image_lookup = {
            img['id']: re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src'])
            for img in p.get('images', [])
        }
        all_imgs_urls = list(image_lookup.values())
        parent_main_img = all_imgs_urls[0] if all_imgs_urls else ""

        # ── 描述 ──
        raw_html = p.get('body_html', '')
        full_desc = clean_html_for_woo(raw_html)
        short_desc = extract_short_desc(raw_html)

        # ── 属性 ──
        options = p.get('options', [])
        opt_configs = [{'name': o['name'], 'values': ", ".join(o['values'])} for o in options]
        while len(opt_configs) < 2:
            opt_configs.append({'name': '', 'values': ''})

        # ── 标签 ──
        tags_str = ", ".join(p.get('tags', [])) if isinstance(p.get('tags'), list) else p.get('tags', '')

        # ── 分类 ──
        product_type = p.get('product_type', '')
        vendor = p.get('vendor', '')
        categories = f"{vendor} > {product_type}" if vendor and product_type else (product_type or vendor or "")

        # ══════════════════════════════════════════════════
        # 父产品行 (Type = variable)
        # ══════════════════════════════════════════════════
        parent_row = {
            "ID": "",
            "Type": "variable",
            "SKU": parent_sku,
            "Name": p['title'],
            "Published": 1,
            "Is featured?": 0,
            "Visibility in catalog": "visible",
            "Short description": short_desc,
            "Description": full_desc,
            "Regular price": clean_price(p['variants'][0]['price']) if p.get('variants') else "",
            "Sale price": "",
            "In stock?": 1,
            "Stock": "",
            "Categories": categories,
            "Tags": tags_str,
            "Images": ",".join(all_imgs_urls),
            "Parent": "",
            "Attribute 1 name": opt_configs[0]['name'],
            "Attribute 1 value(s)": opt_configs[0]['values'],
            "Attribute 1 visible": 1,
            "Attribute 1 global": 1,
            "Attribute 1 default": opt_configs[0]['values'].split(",")[0].strip() if opt_configs[0]['values'] else "",
            "Attribute 2 name": opt_configs[1]['name'],
            "Attribute 2 value(s)": opt_configs[1]['values'],
            "Attribute 2 visible": 1,
            "Attribute 2 global": 1,
            "Meta: _rank_math_title": "",
            "Meta: _rank_math_description": "",
            "Meta: _rank_math_focus_keyword": "",
        }
        extracted.append(parent_row)

        # ══════════════════════════════════════════════════
        # 变体行 (Type = variation)
        # ══════════════════════════════════════════════════
        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
                variant_sku = sku_gen.variant_sku(parent_num, idx)
                v_img = image_lookup.get(v.get('image_id'), parent_main_img)
                in_stock = 1 if v.get('available', True) else 0

                extracted.append({
                    "ID": "",
                    "Type": "variation",
                    "SKU": variant_sku,
                    "Name": f"{p['title']} - {v['title']}",
                    "Published": 1,
                    "Is featured?": 0,
                    "Visibility in catalog": "visible",
                    "Short description": "",
                    "Description": "",
                    "Regular price": clean_price(v.get('price', '')),
                    "Sale price": clean_price(v.get('compare_at_price', '')),
                    "In stock?": in_stock,
                    "Stock": "",
                    "Categories": categories,
                    "Tags": tags_str,
                    "Images": v_img,
                    "Parent": parent_sku,
                    "Attribute 1 name": opt_configs[0]['name'],
                    "Attribute 1 value(s)": v.get('option1', '') if opt_configs[0]['name'] else '',
                    "Attribute 1 visible": 1,
                    "Attribute 1 global": 1,
                    "Attribute 1 default": "",
                    "Attribute 2 name": opt_configs[1]['name'],
                    "Attribute 2 value(s)": v.get('option2', '') if opt_configs[1]['name'] else '',
                    "Attribute 2 visible": 1,
                    "Attribute 2 global": 1,
                    "Meta: _rank_math_title": "",
                    "Meta: _rank_math_description": "",
                    "Meta: _rank_math_focus_keyword": "",
                })
    return extracted


def configure_sku():
    """交互式配置 SKU 规则"""
    print("\n" + "=" * 60)
    print("🔧 SKU 编码规则配置")
    print("=" * 60)
    print()
    print("格式说明:")
    print("  父产品 SKU:   {前缀}-{编号}")
    print("  变体 SKU:     {前缀}-{父编号}-{变体序号}")
    print("  示例: CW-1001       (父产品)")
    print("        CW-1001-1     (变体1)")
    print("        CW-1001-2     (变体2)")
    print()

    while True:
        prefix = input("请输入 SKU 前缀 (例如 CW, MU, MYBRAND, 默认 CW): ").strip().upper()
        if not prefix:
            prefix = "CW"
        if re.match(r'^[A-Z0-9][A-Z0-9\-_]*$', prefix):
            break
        print("❌ 前缀只能包含大写字母、数字、横线和下划线。")

    while True:
        start = input("请输入起始编号 (例如 10000001, 默认 1): ").strip()
        if not start:
            start = "1"
        if start.isdigit() and int(start) >= 1:
            start = str(int(start))
            break
        print("❌ 请输入正整数！")

    sku_gen = SKUGenerator(prefix=prefix, start_num=start)
    print(f"\n✅ SKU 规则已设置: {sku_gen.describe()}")
    return sku_gen


def save_csv(all_data, sku_gen):
    """保存为 WooCommerce 兼容 CSV。列顺序严格按照 CSV_COLUMNS。"""
    parents = [r['SKU'] for r in all_data if r['Type'] == 'variable']
    full_time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"woo_{parents[0]}_to_{parents[-1]}_{full_time_str}.csv"

    df = pd.DataFrame(all_data)
    # 确保列顺序
    df = df[[c for c in CSV_COLUMNS if c in df.columns]]
    df.to_csv(filename, index=False, encoding='utf-8-sig')

    print(f"\n✅ [任务成功]  v{VERSION}")
    print(f"📁 文件保存为: {filename}")
    print(f"📊 共导出 {len(parents)} 个父产品, {len(all_data) - len(parents)} 个变体")
    print(f"📋 列数: {len(df.columns)} (WooCommerce 标准 {len(CSV_COLUMNS)} 列)")
    print(f"💡 建议下次起始编号: {sku_gen.suggest_next_start()}")


def main():
    sku_gen = configure_sku()

    while True:
        print("\n" + "=" * 60)
        print(f"Shopify → WooCommerce  v{VERSION}  (29列标准CSV)")
        print(sku_gen.describe())
        print("=" * 60)
        print()
        print("选项:")
        print("  1. 开始采集")
        print("  2. 修改 SKU 规则")
        print("  3. 退出")
        choice = input("\n请选择 (1/2/3): ").strip()

        if choice == '2':
            sku_gen = configure_sku()
            continue
        elif choice == '3':
            print("👋 再见！")
            break
        elif choice != '1':
            print("❌ 无效选择")
            continue

        # ========== 开始采集 ==========
        url_input = input("\n请输入 Shopify URL: ").strip()
        if not url_input:
            continue

        match = re.search(r'https?://([^/]+)', url_input)
        if not match:
            print("❌ 无法解析 URL，请检查格式。")
            continue
        base_url = f"https://{match.group(1)}"

        all_data = []

        if "/products/" in url_input and ".json" not in url_input:
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            print(f"📦 采集单产品: {product_handle}")
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and data.get('product'):
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
        else:
            if "/collections/" in url_input:
                collection_slug = url_input.split('/collections/')[1].split('/')[0]
                api_path = f"/collections/{collection_slug}/products.json"
            else:
                api_path = "/products.json"

            try:
                max_num = int(input("需要采集多少个父产品? (默认 10): ") or 10)
            except ValueError:
                max_num = 10

            print(f"🔍 开始采集 (最多 {max_num} 个父产品)...")
            page = 1
            while True:
                parent_count = len([i for i in all_data if i.get('Type') == 'variable'])
                if parent_count >= max_num:
                    break

                data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
                if not data:
                    print(f"  ❌ 第{page}页请求失败，采集中断。")
                    break
                products = data.get('products')
                if not products:
                    print(f"  📭 第{page}页无产品，已到达目录末尾。")
                    break

                remaining = max_num - parent_count
                all_data.extend(process_to_woo_format(products, remaining, sku_gen))
                new_count = len([i for i in all_data if i.get('Type') == 'variable'])
                print(f"  📄 第{page}页 — API返回{len(products)}个, 已采集 {new_count}/{max_num} 个父产品")
                page += 1

            parent_count = len([i for i in all_data if i.get('Type') == 'variable'])
            if parent_count < max_num and page > 1:
                print(f"  ⚠️ 注意: 请求了{max_num}个，但站点仅有{parent_count}个父产品。")

        if all_data:
            save_csv(all_data, sku_gen)
        else:
            print("\n⚠️ 未采集到任何数据，请检查 URL 是否正确。")

        again = input("\n输入 'r' 重新采集，输入 's' 修改SKU规则，其他键退出: ").lower()
        if again == 's':
            sku_gen = configure_sku()
        elif again != 'r':
            break


if __name__ == "__main__":
    main()
