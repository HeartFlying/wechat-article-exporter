#!/usr/bin/env python3
"""
使用 PyInstaller 打包 wechat-fetcher 为独立可执行文件。

用法:
    python build_exe.py          # 打包为目录（推荐，启动快）
    python build_exe.py --onefile # 打包为单文件（启动慢，文件大）
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def clean_build():
    """清理之前的构建文件。"""
    dirs_to_remove = ['build', 'dist']
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            print(f"清理 {dir_name}/ ...")
            shutil.rmtree(dir_name)
    
    # 清理 spec 文件
    for spec_file in Path('.').glob('*.spec'):
        print(f"清理 {spec_file} ...")
        spec_file.unlink()


def get_hidden_imports():
    """获取需要显式导入的隐藏依赖。"""
    hiddenimports = [
        # Python 3.13+ 移除的模块
        'imghdr',
        # mitmproxy 相关
        'mitmproxy',
        'mitmproxy.proxy',
        'mitmproxy.proxy.server',
        'mitmproxy.proxy.layers',
        'mitmproxy.addons',
        'mitmproxy.addons.core',
        'mitmproxy.addons.proxyauth',
        'mitmproxy.addons.termlog',
        'mitmproxy.addons.readfile',
        'mitmproxy.addons.dumper',
        'mitmproxy.addons.termstatus',
        'mitmproxy.addons.view',
        'mitmproxy.addons.intercept',
        'mitmproxy.addons.browser',
        'mitmproxy.addons.export',
        'mitmproxy.addons.onboarding',
        'mitmproxy.addons.eventstore',
        'mitmproxy.addons.asgiapp',
        'mitmproxy.addons.maplocal',
        'mitmproxy.addons.mapremote',
        'mitmproxy.addons.modifybody',
        'mitmproxy.addons.modifyheaders',
        'mitmproxy.addons.stickyauth',
        'mitmproxy.addons.stickycookie',
        'mitmproxy.addons.streambodies',
        'mitmproxy.addons.save',
        'mitmproxy.addons.upstream_auth',
        'mitmproxy.addons.disable_h2c',
        'mitmproxy.addons.block',
        'mitmproxy.addons.anticomp',
        'mitmproxy.addons.check_ca',
        'mitmproxy.addons.tlsconfig',
        'mitmproxy.addons.clientplayback',
        'mitmproxy.addons.serverplayback',
        'mitmproxy.addons.state',
        'mitmproxy.addons.web',
        # 其他依赖
        'click',
        'requests',
        'bs4',
        'markdownify',
        'certifi',
        'urllib3',
        'charset_normalizer',
        'idna',
        # 加密相关
        'cryptography',
        'OpenSSL',
        # 网络相关
        'h2',
        'hpack',
        'hyperframe',
        'wsproto',
        'h11',
        'kaitaistruct',
        'ldap3',
        'pyasn1',
        'publicsuffix2',
        'pydivert',
        'Brotli',
        'zstandard',
        'tornado',
        'flask',
        'jinja2',
        'werkzeug',
        'itsdangerous',
        'markupsafe',
        'asgiref',
        'blinker',
        'passlib',
        'ruamel.yaml',
        'sortedcontainers',
        'urwid',
        'pyperclip',
        'msgpack',
        'protobuf',
        'pyparsing',
        'cffi',
        'pycparser',
        'six',
        'typing_extensions',
        'colorama',
    ]
    return hiddenimports


def get_datas():
    """获取需要包含的数据文件。"""
    datas = []

    # 添加 wechat_fetcher 包中的 proxy_addon.py（单文件模式需要）
    wechat_fetcher_dir = Path('wechat_fetcher')
    if wechat_fetcher_dir.exists():
        proxy_addon = wechat_fetcher_dir / 'proxy_addon.py'
        if proxy_addon.exists():
            datas.append((str(proxy_addon), 'wechat_fetcher'))

    # 添加 mitmproxy 的静态文件
    try:
        import mitmproxy
        mitmproxy_root = Path(mitmproxy.__file__).parent
        # 添加 onboarding 页面（CA 证书下载页面）
        onboarding = mitmproxy_root / 'addons' / 'onboardingapp'
        if onboarding.exists():
            datas.append((str(onboarding), 'mitmproxy/addons/onboardingapp'))
        # 添加静态资源
        static = mitmproxy_root / 'tools' / 'web' / 'static'
        if static.exists():
            datas.append((str(static), 'mitmproxy/tools/web/static'))
        templates = mitmproxy_root / 'tools' / 'web' / 'templates'
        if templates.exists():
            datas.append((str(templates), 'mitmproxy/tools/web/templates'))
    except ImportError:
        print("警告: 无法找到 mitmproxy 静态文件")

    # 添加 certifi 证书
    try:
        import certifi
        cert_path = certifi.where()
        datas.append((cert_path, 'certifi'))
    except ImportError:
        pass

    return datas


def build(onefile=False):
    """执行 PyInstaller 打包。"""
    clean_build()
    
    print("开始打包 wechat-fetcher ...")
    print(f"模式: {'单文件' if onefile else '目录'}")
    
    # 构建命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name=wechat-fetcher',
        '--noconfirm',
        '--clean',
    ]
    
    if onefile:
        cmd.append('--onefile')
    else:
        cmd.append('--onedir')
    
    # 添加隐藏导入
    for imp in get_hidden_imports():
        cmd.extend(['--hidden-import', imp])
    
    # 添加数据文件
    for src, dst in get_datas():
        cmd.extend(['--add-data', f'{src}{os.pathsep}{dst}'])
    
    # 其他选项
    cmd.extend([
        '--collect-all', 'mitmproxy',
        '--collect-all', 'requests',
        '--collect-all', 'bs4',
        '--collect-all', 'markdownify',
        '--collect-all', 'click',
        '--collect-all', 'certifi',
    ])
    
    # 入口脚本
    cmd.append('wechat_fetcher/__main__.py')
    
    print(f"执行命令: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print()
        print("=" * 60)
        print("打包成功!")
        print("=" * 60)
        if onefile:
            print(f"输出: dist/wechat-fetcher.exe")
        else:
            print(f"输出: dist/wechat-fetcher/wechat-fetcher.exe")
        print()
        print("使用说明:")
        print("1. 将整个 dist/wechat-fetcher 目录分发给用户")
        print("2. 用户无需安装 Python，直接运行 wechat-fetcher.exe")
        print("3. 数据会存储在用户目录 ~/.wechat-fetcher/")
    else:
        print()
        print("=" * 60)
        print("打包失败!")
        print("=" * 60)
        sys.exit(1)


def main():
    """主函数。"""
    onefile = '--onefile' in sys.argv or '-F' in sys.argv
    
    # 检查 PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未安装 PyInstaller")
        print("请运行: pip install pyinstaller")
        sys.exit(1)
    
    build(onefile=onefile)


if __name__ == '__main__':
    main()
