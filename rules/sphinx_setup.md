# 初期設定メモ

## Sphinxドキュメント設定

### 1. 必要なパッケージのインストール

```bash
uv pip install sphinx sphinx-rtd-theme
```

### 2. Sphinxプロジェクトの初期化

```bash
mkdir docs
cd docs
sphinx-quickstart
```

以下の質問に対する推奨回答：
- Separate source and build directories (y/n) [n]: y
- Project name: [プロジェクト名]
- Author name(s): [著者名]
- Project release []: 0.1.0
- Project language [en]: ja

### 3. conf.pyの設定

```python
import os
import sys
import subprocess

# ソースコードのパスを追加（プロジェクトの構造に応じて調整）
sys.path.insert(0, os.path.abspath("../src/[プロジェクト名]"))

def get_version():
    try:
        # 最新のgit tagを取得
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"], universal_newlines=True
        ).strip()
        return tag
    except subprocess.CalledProcessError:
        # git tagが存在しない場合はデフォルトのバージョンを返す
        return "0.1.0"

# プロジェクト情報
project = "[プロジェクト名]"
copyright = "2024, [著者名]"
author = "[著者名]"
version = get_version()  # git tagから動的に取得
release = version       # 通常はversionと同じ値を使用

# 拡張機能の設定
extensions = [
    "sphinx.ext.autodoc",     # APIドキュメント自動生成
    "sphinx.ext.napoleon",    # Google/NumPyスタイルのdocstring対応
    "sphinx.ext.viewcode",    # ソースコードへのリンク
    "sphinx.ext.intersphinx", # 外部プロジェクトへのリンク
    "myst_parser",           # Markdownサポート
]

# テンプレートとパターンの設定
templates_path = ["_templates"]
exclude_patterns = []

# Intersphinx設定
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# HTMLテーマ設定
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

# テーマオプション
html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
    "style_external_links": True,
    "prev_next_buttons_location": "both",
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
}
```

### 4. index.rstの基本構成

```rst
[プロジェクト名] ドキュメント
========================

バージョン: |version|

[プロジェクトの説明]

主な機能
--------

- 機能1
- 機能2
- 機能3

目次
----

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   modules/[モジュール名]

インデックス
------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
```

### 5. モジュールドキュメントの作成

`docs/source/modules/[モジュール名].rst`の基本構成：

```rst
モジュール名
===========

.. module:: [プロジェクト名].[モジュール名]

このモジュールの説明をここに記述します。

関数名
------

.. autofunction:: [プロジェクト名].[モジュール名].[関数名]

クラス
------

.. autoclass:: [プロジェクト名].[モジュール名].[クラス名]
   :members:
   :undoc-members:
```

### 6. ドキュメントのビルド

```bash
cd docs
uv run sphinx-build -b html source build
```

生成されたドキュメントは`docs/build/index.html`で確認できます。

macOSの場合：
```bash
open build/index.html
```

### 7. バージョン管理

- バージョン情報は`conf.py`の`get_version()`関数でgit tagから自動的に取得されます
- タグが存在しない場合は、デフォルトのバージョン（0.1.0）が表示されます
- 新しいバージョンのタグはGitHub Actionsで自動的に作成されます
  - リリース用のPRがマージされると、GitHub Actionsが自動的にタグを作成
  - タグの作成は手動では行わない

### 注意点

1. docstringはGoogle形式を推奨
   ```python
   def function(arg1: str, arg2: int) -> bool:
       """関数の説明

       Args:
           arg1: 引数1の説明
           arg2: 引数2の説明

       Returns:
           戻り値の説明

       Raises:
           ValueError: エラーの説明
       """
       pass
   ```

2. 日本語ドキュメントを書く場合は、docstringも日本語で統一

3. モジュールのインポートエラーが発生する場合は、`conf.py`のパス設定を確認

4. 画像やその他の静的ファイルは`_static`ディレクトリに配置 