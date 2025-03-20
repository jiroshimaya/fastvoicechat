# 初期設定メモ

# リポジトリ構成

以下のような構成を前提とします。

```
fastvoicechat/
├── src/
│   └── fastvoicechat/
│       └── __init__.py
├── docs/
│   ├── source/
│   │   ├── conf.py
│   │   ├── index.rst
│   │   └── modules/
│   └── build/
├── tests/
├── pyproject.toml
└── README.md
```

主なポイント：
- ソースコードは`src/fastvoicechat/`に配置
- ドキュメントは`docs/`ディレクトリに配置
  - `source/`: RSTファイルや設定ファイル
  - `build/`: ビルドされたHTMLファイル
- テストは`tests/`ディレクトリに配置
- 依存関係は`pyproject.toml`で管理

# Sphinx導入手順

## 1. 必要なパッケージのインストール

```sh
uv add sphinx sphinx-rtd-theme autodoc-pydantic --dev
```
## 2. Sphinxの初期設定

1. プロジェクトのルートディレクトリで以下のコマンドを実行してSphinxを初期化します：

```bash
uv run sphinx-quickstart docs
```

2. 対話形式で以下のような質問が表示されます：
   - Separate source and build directories (y/n) [n]: y
   - Project name: FastVoiceChat
   - Author name(s): shimajiroxyz
   - Project release []: 0.1.0
   - Project language [en]: ja

## 3. 設定ファイル

### conf.py
`docs/source/conf.py`を以下のようにする

```python
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath("../../src"))


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


# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "FastVoiceChat"
copyright = "2025, shimajiroxyz"
author = "shimajiroxyz"
version = get_version()
release = version
language = "ja"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",  # ソースコード読み込み用
    "sphinx.ext.napoleon",  # docstring パース用
    "sphinxcontrib.autodoc_pydantic",  # pydanticのドキュメント生成用
]


templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
# -- Options for sphinx-multiversion -----------------------------------------
```

ポイントは以下。

- versionはget_version関数でgitのtagから自動で取得
- extensionsは`autodoc`、`napoleon`、`autodoc-pydantic`の３つ。
- html_themeに`sphinx_rtd_theme`を使用

### index.rst

`docs/source/index.rst`を以下のようにする。

```rst
.. fastvoicechat documentation master file, created by
   sphinx-quickstart on Wed Mar 19 17:33:32 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

FastVoiceChat ドキュメント
===================================

バージョン: |version|

（プロジェクトの概要）

主な機能
--------

- 機能1
- 機能2

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   modules
```

主なポイントは以下

- toctreeに`modules`を追加。これは後にautodocで自動生成されるrstの名前。


## 4. APIドキュメントの自動生成

ソースコードのツリー構造をそのままAPIドキュメントに変換する。

```sh
uv run sphinx-apidoc -f -o docs/source src/fastvoicechat
```

docs/sourceにモジュールごとのrstファイルとmodule.rstが生成される。


## 5. ビルドと確認

1. ドキュメントのビルド：

```bash
cd docs
uv run make clean html
```

2. ビルドされたドキュメントは `docs/build/html/` に生成されます。

3. ローカルで確認する場合：

```bash
open build/html/index.html
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
