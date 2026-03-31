import re

with open("public/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Replace <style>...</style> block with <link>
html = re.sub(r'<style>.*?</style>', '<link rel="stylesheet" href="/style.css">', html, flags=re.DOTALL)

# Wrap tabs in #tabs-wrapper
old_tabs = '''<!-- BOTTOM TABS -->
  <div id="tabs">
    <button class="tb on" data-tab="dash"><span class="ti">📊</span><span class="tl">Dashboard</span></button>
    <button class="tb" data-tab="analysis"><span class="ti">🤖</span><span class="tl">Analisi</span></button>
    <button class="tb" data-tab="journal"><span class="ti">📓</span><span class="tl">Journal</span></button>
    <button class="tb" data-tab="kb"><span class="ti">📚</span><span class="tl">Apprendi</span></button>
    <button class="tb" data-tab="myfx"><span class="ti">📈</span><span class="tl">MyFxBook</span></button>
  </div>'''

new_tabs = '''<!-- BOTTOM TABS -->
  <div id="tabs-wrapper">
    <div id="tabs">
      <button class="tb on" data-tab="dash"><span class="ti">📊</span><span class="tl">Dashboard</span></button>
      <button class="tb" data-tab="analysis"><span class="ti">🤖</span><span class="tl">Analisi</span></button>
      <button class="tb" data-tab="journal"><span class="ti">📓</span><span class="tl">Journal</span></button>
      <button class="tb" data-tab="kb"><span class="ti">📚</span><span class="tl">Apprendi</span></button>
      <button class="tb" data-tab="myfx"><span class="ti">📈</span><span class="tl">MyFxBook</span></button>
    </div>
  </div>'''

html = html.replace(old_tabs, new_tabs)

with open("public/index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Updated index.html")
