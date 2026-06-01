import re

with open("public/index.html", "r", encoding="utf-8") as f:
    text = f.read()

# Replace prices with skeletons
text = re.sub(r'<div class="pc-val" id="([a-zA-Z0-9-]+)">—</div>', r'<div class="pc-val" id="\1"><div class="skel" style="width:40px;height:14px;margin:4px 0"></div></div>', text)
text = re.sub(r'<div class="pc-chg" id="([a-zA-Z0-9-]+)">—</div>', r'<div class="pc-chg" id="\1"><div class="skel" style="width:30px;height:10px;margin:2px 0"></div></div>', text)

# Replace macro with skeletons
text = re.sub(r'<span id="us10y-val" style="[^"]+">—%</span>', r'<span id="us10y-val" style="font-size:13px;font-weight:700"><div class="skel" style="width:30px;height:14px;display:inline-block"></div></span>', text)
text = re.sub(r'<span id="gsr-val" style="[^"]+">—</span>', r'<span id="gsr-val" style="font-size:13px;font-weight:700"><div class="skel" style="width:30px;height:14px;display:inline-block"></div></span>', text)
text = re.sub(r'<span id="cot-net" style="[^"]+">—K</span>', r'<span id="cot-net" style="font-size:13px;font-weight:700"><div class="skel" style="width:40px;height:14px;display:inline-block"></div></span>', text)

# Replace conf num
text = text.replace('<div class="conf-num" id="conf-num">—</div>', '<div class="conf-num" id="conf-num"><div class="skel" style="width:24px;height:18px"></div></div>')

with open("public/index.html", "w", encoding="utf-8") as f:
    f.write(text)

print("Skeletons applied")
