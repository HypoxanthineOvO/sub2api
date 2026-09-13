#!/usr/bin/env python3
"""Exercise the real Vue component against synthetic metadata on a local Vite server."""
import json
import os
import tomllib
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'
OUTPUT = ROOT / 'dist/validation/key-access'
FIXTURE = FRONTEND / '.vsp-key-access-test.html'
HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body><div id="app"></div><script type="module">
import {createApp, ref, h} from 'vue'; import {createPinia} from 'pinia';
import i18n, {initI18n} from '/src/i18n/index.ts';
import Modal from '/src/features/vsp-key-access/KeyAccessModal.vue'; import '/src/style.css';
localStorage.setItem('sub2api_locale','zh'); await initI18n(); i18n.global.locale.value='zh';
createApp({setup(){const show=ref(false); return ()=>h('div',[
h('button',{class:'btn btn-primary',onClick:()=>show.value=true},'打开测试弹窗'),
h(Modal,{show:show.value,apiKey:'sk-example-only',baseUrl:'https://api.vsplab.tech',platform:'anthropic',onClose:()=>show.value=false})
])}
}).use(createPinia()).use(i18n).mount('#app');
</script></body></html>'''


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(os.environ['CATALOG_FILE']).read_text()) if os.environ.get('CATALOG_FILE') else {
        'version': 1, 'models': [{'id': 'offline-example', 'protocol': 'openai'}, {'id': 'hidden-example', 'hidden': True, 'protocol': 'anthropic'}]
    }
    model_ids = [model['id'] for model in data['models']]
    with FIXTURE.open('x') as file:
        file.write(HTML)
    requests = []
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_EXECUTABLE'))
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'], viewport={'width': 1100, 'height': 850})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))

            def route(request):
                url = request.request.url
                if url.startswith('http://127.0.0.1:5120/'):
                    request.continue_()
                elif url == 'https://api.vsplab.tech/vsp/models':
                    requests.append(request.request.headers)
                    request.fulfill(content_type='application/json', headers={'Access-Control-Allow-Origin': '*'}, body=json.dumps(data))
                else:
                    request.abort()
            page.route('**/*', route)
            page.goto('http://127.0.0.1:5120/.vsp-key-access-test.html')
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='打开测试弹窗').click()
            dialog = page.get_by_role('dialog')
            dialog.wait_for()
            assert 'sk-example-only' not in dialog.inner_text()
            assert not requests
            page.get_by_role('button', name='复制 BaseURL + APIKey', exact=True).click()
            assert page.evaluate('navigator.clipboard.readText()') == 'BaseURL: https://api.vsplab.tech, APIKey: sk-example-only'
            page.screenshot(path=str(OUTPUT / 'credentials-desktop.png'))
            page.set_viewport_size({'width': 375, 'height': 812})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUTPUT / 'credentials-mobile.png'))
            page.get_by_role('button', name='客户端配置', exact=True).click()
            page.get_by_role('button', name='复制完整目录 JSON').wait_for()
            assert len(dialog.locator('button[aria-pressed]').all()) == 6
            assert all('authorization' not in headers and 'cookie' not in headers for headers in requests)
            page.get_by_role('button', name='Pi', exact=True).click()
            pi = json.loads(dialog.locator('pre').first.inner_text())
            assert sorted(model['id'] for provider in pi['providers'].values() for model in provider['models']) == sorted(model_ids)
            for client in ['Codex', 'VSP-Codex', 'VSPi', 'Kimi Code']:
                page.get_by_role('button', name=client, exact=True).click()
                config = tomllib.loads(dialog.locator('pre').first.inner_text())
                assert config
                if client == 'Kimi Code':
                    assert sorted(model['model'] for model in config['models'].values()) == sorted(model_ids)
            page.get_by_role('button', name='Pi', exact=True).click()
            page.evaluate("document.documentElement.classList.add('dark')")
            page.wait_for_function("getComputedStyle(document.querySelector('[aria-pressed=true]')).color === 'rgb(255, 255, 255)'")
            page.screenshot(path=str(OUTPUT / 'clients-mobile-dark.png'))
            page.keyboard.press('Escape')
            dialog.wait_for(state='hidden')
            assert not errors, errors
            context.close(); browser.close()
        print('PASS: masked credentials, exact clipboard, no default fetch, six clients, full catalog, no auth headers, mobile layout, Escape; screenshots saved')
    finally:
        if errors:
            print('Browser errors:', errors)
        FIXTURE.unlink()


if __name__ == '__main__': main()
