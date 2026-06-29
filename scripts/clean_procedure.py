# scripts/clean_procedure.py
"""把 CNIPA 办事指南导出的 md 清理成结构规整的 procedure 语料。
用法: python scripts/clean_procedure.py raw.md knowledge/procedure/专利.md [--strip-contact]
"""
import re, sys, argparse

# ---------- 1. 全角→半角(只挑安全的:数字/字母/.／＠等;不动 Chinese ：（），。) ----------
_FW = {}
for i in range(10):  _FW[chr(0xFF10+i)] = str(i)            # ０-９
for i in range(26):
    _FW[chr(0xFF21+i)] = chr(ord('A')+i)                    # Ａ-Ｚ
    _FW[chr(0xFF41+i)] = chr(ord('a')+i)                    # ａ-ｚ
_FW.update({'／':'/', '．':'.', '＠':'@', '－':'-', '＿':'_',
            '＂':'"', '～':'~', '＃':'#', '％':'%', '＆':'&', '＝':'=', '？':'?'})
_FW_TABLE = str.maketrans(_FW)   # 注意:故意不含全角冒号 ： 和全角括号 （），保留中文排版

def normalize(s: str) -> str:
    s = s.translate(_FW_TABLE)
    s = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', s)               # "1 5 日"->"15 日"、"（ 010 ）"->"（010）"
    s = _repair_urls(s)
    return s

# ---------- 2. URL / 邮箱修复(全角冒号、token 内空格、跨行断裂) ----------
def _repair_urls(s: str) -> str:
    # 2a. 邮箱:把 ＠ 已转 @,顺手去 token 内空格
    s = re.sub(r'([A-Za-z0-9._-]+)\s*@\s*([A-Za-z0-9.]+)', r'\1@\2', s)
    # 2b. URL:从 http 起,尽量吃到下个中文标点/空白前;期间去内部空格、修 scheme 冒号
    def fix(m):
        url = m.group(0)
        url = re.sub(r'^(https?)[：:]', r'\1:', url)         # https：// -> https://
        url = re.sub(r'\s+', '', url)                       # 去 OCR 夹入的空格/断行
        return url
    s = re.sub(r'https?[：:]\s*/\s*/\s*[\w.\-/～~#%&=?]+(?:\s+[\w.\-/～~#%&=?]+)*', fix, s)
    return s

# ---------- 3. 标题前缀分类(核心:层级靠编号,不靠 # 数量) ----------
ITEM   = re.compile(r'^[一二三四五六七八九十百零]+、')        # 事项  -> H2
SUBSEC = re.compile(r'^（[一二三四五六七八九十]+）')          # 小节  -> H3
STEP   = re.compile(r'^\d+[.．]')                            # 步骤  -> H4
PSTEP  = re.compile(r'^（\d+）')                             # （1）子步骤 -> H5
TITLE  = ('知识产权政务服务事项办事指南', '（第二版）')

# ---------- 4. 噪声行(可选 --strip-contact;默认保留,交给入库管线过滤) ----------
NOISE = [re.compile(p) for p in (
    r'^\s*(联系电话|咨询电话|电话咨询|电话投诉|传真|当面咨询|当面投诉)[：:]',
    r'邮政编码[：:]?\s*\d{6}', r'邮编[：:]?\s*\d{6}',
    r'^\s*(邮寄地址|地址|通讯地址)[：:]',
)]

def clean(text: str, strip_contact: bool = False) -> str:
    out, in_toc = [], False
    for raw in text.split('\n'):
        for line in raw.split('<br>'):          # Notion 导出的软换行
            line = line.rstrip()
            if not line:
                continue
            is_head = line.startswith('#')
            body = line.lstrip('#').strip() if is_head else line
            # 跳过目录块:遇到"目录"标题开始,直到第一个事项标题结束
            if is_head and body.startswith('目录'):
                in_toc = True; continue
            if in_toc:
                if is_head and ITEM.match(body): in_toc = False
                else: continue
            if is_head:
                if body in TITLE:        out.append(f'# {body}')
                elif ITEM.match(body):   out.append(f'\n## {normalize(body)}')
                elif SUBSEC.match(body): out.append(f'### {normalize(body)}')
                elif STEP.match(body):   out.append(f'#### {normalize(body)}')
                elif PSTEP.match(body):  out.append(f'##### {normalize(body)}')
                else:                    out.append(f'### {normalize(body)}')  # 兜底
            else:
                n = normalize(line)
                if strip_contact and any(p.search(n) for p in NOISE):
                    continue
                out.append(n)
    return '\n'.join(out) + '\n'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--strip-contact', action='store_true')
    a = ap.parse_args()
    with open(a.src, encoding='utf-8') as f: text = f.read()
    res = clean(text, a.strip_contact)
    with open(a.dst, 'w', encoding='utf-8') as f: f.write(res)
    print(f'done -> {a.dst} ({len(res)} chars)')

if __name__ == '__main__':
    main()