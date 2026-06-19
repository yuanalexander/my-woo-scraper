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
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tags in soup(["script", "style", "iframe", "button", "input", "header", "footer", "nav"]):
        tags.decompose()
    for tag in soup.find_all(True):
        tag.attrs = {}
    cleaned = str(soup).replace('\n', ' ').replace('\r', '').strip()
    return " ".join(cleaned.split())


def get_data(api_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求失败: {e}")
        return None


class SKUGenerator:
    """
    可自定义 SKU 编码规则。
    
    默认格式:
      父产品:  {prefix}-{number}
      变体:    {prefix}-{parent_number}-{variant_index}
    
    示例:
      prefix="CW", start=10000001  →  父: CW-10000001,  变体: CW-10000001-1
      prefix="MU", start=5001      →  父: MU-5001,       变体: MU-5001-1
      prefix="BRAND-A", start=1    →  父: BRAND-A-1,     变体: BRAND-A-1-1
    """

    def __init__(self, prefix="CW", start_num=1):
        self.prefix = str(prefix).strip()
        if not self.prefix:
            self.prefix = "CW"
        self.counter = int(start_num) - 1

    @property
    def current_number(self):
        """返回当前计数器值（下一个要用的数字 - 1）"""
        return self.counter

    def next_parent_sku(self):
        """生成下一个父产品 SKU"""
        self.counter += 1
        return f"{self.prefix}-{self.counter}"

    def variant_sku(self, parent_num, variant_index):
        """根据父产品数字和变体序号生成变体 SKU"""
        return f"{self.prefix}-{parent_num}-{variant_index}"

    def suggest_next_start(self):
        """建议下一个采集批次的起始序号"""
        return self.counter + 1

    def describe(self):
        """返回当前 SKU 规则描述"""
        return f"前缀: {self.prefix}  |  父SKU格式: {self.prefix}-XXXX  |  变体SKU格式: {self.prefix}-XXXX-N"


def process_to_woo_format(products, limit, sku_gen):
    extracted = []
    for p in products:
        parent_count = len([item for item in extracted if item.get('Type') == 'variable'])
        if parent_count >= limit:
            break

        parent_sku = sku_gen.next_parent_sku()
        parent_num = sku_gen.current_number  # 当前已分配的数字

        # 变体图片精准映射
        image_lookup = {
            img['id']: re.sub(r'(_\d+x\d+|_small|_medium|_large|_grande)\.', '.', img['src'])
            for img in p.get('images', [])
        }
        all_imgs_urls = list(image_lookup.values())
        parent_main_img = all_imgs_urls[0] if all_imgs_urls else ""

        full_desc = clean_html_for_woo(p.get('body_html', ''))
        options = p.get('options', [])
        opt_configs = [{'name': o['name'], 'values': ", ".join(o['values'])} for o in options]
        while len(opt_configs) < 3:
            opt_configs.append({'name': '', 'values': ''})

        # 父产品行
        extracted.append({
            'Type': 'variable',
            'SKU': parent_sku,
            'Name': p['title'],
            'Published': 1,
            'Description': full_desc,
            'In stock?': 1,
            'Regular price': p['variants'][0]['price'] if p['variants'] else '',
            'Categories': p.get('product_type', ''),
            'Images': ",".join(all_imgs_urls),
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
        })

        # 变体行
        if p.get('variants'):
            for idx, v in enumerate(p['variants'], 1):
                variant_sku = sku_gen.variant_sku(parent_num, idx)
                v_img = image_lookup.get(v.get('image_id'), parent_main_img)
                extracted.append({
                    'Type': 'variation',
                    'SKU': variant_sku,
                    'Name': f"{p['title']} - {v['title']}",
                    'Published': 1,
                    'In stock?': 1,
                    'Regular price': v['price'],
                    'Images': v_img,
                    'Parent': parent_sku,
                    'Attribute 1 name': opt_configs[0]['name'],
                    'Attribute 1 value(s)': v.get('option1', '') if opt_configs[0]['name'] else '',
                    'Attribute 2 name': opt_configs[1]['name'],
                    'Attribute 2 value(s)': v.get('option2', '') if opt_configs[1]['name'] else '',
                    'Attribute 3 name': opt_configs[2]['name'],
                    'Attribute 3 value(s)': v.get('option3', '') if opt_configs[2]['name'] else '',
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
    print("  示例: MU-1001       (父产品)")
    print("        MU-1001-1     (变体1: 颜色/尺码)")
    print("        MU-1001-2     (变体2: 颜色/尺码)")
    print()

    # 前缀
    while True:
        prefix = input("请输入 SKU 前缀 (例如 CW, MU, MYBRAND, 默认 CW): ").strip().upper()
        if not prefix:
            prefix = "CW"
        if re.match(r'^[A-Z0-9][A-Z0-9\-_]*$', prefix):
            break
        print("❌ 前缀只能包含大写字母、数字、横线和下划线，且不能为空。")

    # 起始编号
    while True:
        start = input("请输入起始编号 (例如 10000001, 默认 1): ").strip()
        if not start:
            start = "1"
        if start.isdigit() and int(start) >= 1:
            start = str(int(start))  # 去前导零
            break
        print("❌ 请输入正整数！")

    sku_gen = SKUGenerator(prefix=prefix, start_num=start)
    print(f"\n✅ SKU 规则已设置: {sku_gen.describe()}")
    return sku_gen


def main():
    # 首次配置 SKU 规则
    sku_gen = configure_sku()

    while True:
        print("\n" + "=" * 60)
        print("Shopify To WooCommerce v16.0 (自定义SKU版)")
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

        # 判断是单产品还是集合
        if "/products/" in url_input and ".json" not in url_input:
            # 单产品模式
            product_handle = url_input.split("/products/")[1].split("?")[0].split("#")[0]
            print(f"📦 采集单产品: {product_handle}")
            data = get_data(f"{base_url}/products/{product_handle}.json")
            if data and data.get('product'):
                all_data = process_to_woo_format([data['product']], 1, sku_gen)
        else:
            # 集合/全站模式
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
            while len([i for i in all_data if i.get('Type') == 'variable']) < max_num:
                data = get_data(f"{base_url}{api_path}?limit=250&page={page}")
                if not data or not data.get('products'):
                    break
                all_data.extend(process_to_woo_format(data['products'], max_num, sku_gen))
                current_count = len([i for i in all_data if i.get('Type') == 'variable'])
                print(f"  📄 第{page}页 — 已采集 {current_count} 个产品...")
                page += 1

        # 保存结果
        if all_data:
            parents = [r['SKU'] for r in all_data if r['Type'] == 'variable']
            full_time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"woo_{parents[0]}_to_{parents[-1]}_{full_time_str}.csv"

            pd.DataFrame(all_data).to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n✅ [任务成功]")
            print(f"📁 文件保存为: {filename}")
            print(f"📊 共导出 {len(parents)} 个父产品, {len(all_data) - len(parents)} 个变体")
            print(f"💡 建议下次起始编号: {sku_gen.suggest_next_start()}")
        else:
            print("\n⚠️ 未采集到任何数据，请检查 URL 是否正确。")

        # 继续 or 退出
        again = input("\n输入 'r' 重新采集，输入 's' 修改SKU规则，其他键退出: ").lower()
        if again == 's':
            sku_gen = configure_sku()
        elif again != 'r':
            break


if __name__ == "__main__":
    main()
