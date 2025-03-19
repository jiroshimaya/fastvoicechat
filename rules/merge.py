from pathlib import Path
from typing import Any, Dict

# mdcファイルとmdディレクトリの対応関係の定義
MDC_CONFIGURATIONS = [
    {
        "output": ".cursor/rules/000_bestpractices.mdc",
        "source_dir": "rules",
        "header": "",  # もしコメントとか入れたければ
        "file_pattern": "*.md",
        "sort_by": "name",
    },
    {
        "output": ".cursor/rules/000_general.mdc",
        "source_dir": "rules/general",
        "header": "",  # もしコメントとか入れたければ
        "file_pattern": "*.md",
        "sort_by": "name",
    },
    {
        "output": ".cursor/rules/001_bestPractices_common.mdc",
        "source_dir": "rules/common",
        "header": "",  # もしコメントとか入れたければ
        "file_pattern": "*.md",
        "sort_by": "name",
    },
]


def extract_number_prefix(filename: str) -> float:
    """ファイル名から数字プレフィックスを抽出してソートするための関数"""
    import re

    match = re.match(r"^(\d+)_", filename)
    return int(match.group(1)) if match else float("inf")


def build_mdc_file(config: Dict[str, Any]) -> None:
    """mdファイルを検索して結合する関数"""
    # ルートディレクトリの取得（スクリプトの実行場所から相対パスで計算）
    root_dir = Path.cwd()

    # mdファイルのパターンを作成
    source_dir = root_dir / config["source_dir"]

    # mdファイルを検索
    files = list(source_dir.glob(config["file_pattern"]))

    # ファイル名でソート
    files.sort(key=lambda x: extract_number_prefix(x.name))

    # コンテンツの初期化
    content = config["header"]

    # 各mdファイルの内容を結合
    for file in files:
        file_content = file.read_text(encoding="utf-8")
        content += file_content + "\n\n"

    # 出力パスの設定
    output_path = root_dir / config["output"]

    # 出力ディレクトリが存在することを確認
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ファイルに書き込み
    output_path.write_text(content, encoding="utf-8")

    print(
        f"Generated {config['output']} from {len(files)} files in {config['source_dir']}"
    )


def clean_mdc_files() -> None:
    """既存のMDCファイルの中身を空にする関数"""
    rules_dir = Path(".cursor/rules")

    # ディレクトリが存在しない場合は何もしない
    if not rules_dir.exists():
        return

    # .mdc ファイルを検索して中身を空にする
    for mdc_file in rules_dir.glob("*.mdc"):
        print(f"Clearing content of MDC file: {mdc_file}")
        mdc_file.write_text("")  # ファイルの中身を空にする


def main() -> None:
    """メイン処理"""
    try:
        # 既存のMDCファイルを削除
        clean_mdc_files()

        # 各設定に対してmdcファイルを生成
        for config in MDC_CONFIGURATIONS:
            build_mdc_file(config)
        print("All mdc files have been successfully generated!")
    except Exception as e:
        print(f"Error generating mdc files: {e}")
        exit(1)


if __name__ == "__main__":
    main()
