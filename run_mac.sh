#!/bin/bash

echo "========================================="
echo "  Telegram to Slack 転送ツール"
echo "========================================="
echo ""

# 仮想環境が存在するかチェック
if [ ! -d "venv" ]; then
    echo "⚠️  仮想環境が見つかりません"
    echo "セットアップを開始します..."
    echo ""

    # Python バージョンチェック
    echo "Python のバージョンを確認しています..."
    python_version=$(python3 --version 2>&1 | awk '{print $2}')
    echo "Python バージョン: $python_version"

    # Python 3.9 以上かチェック
    required_version="3.9"
    if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
        echo "エラー: Python 3.9 以上が必要です"
        exit 1
    fi

    echo "✓ Python バージョン OK"
    echo ""

    # 仮想環境の作成
    echo "仮想環境を作成しています..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "✗ 仮想環境の作成に失敗しました"
        exit 1
    fi
    echo "✓ 仮想環境の作成が完了しました"
    echo ""

    # 仮想環境を有効化
    echo "仮想環境を有効化しています..."
    source venv/bin/activate

    # 依存パッケージのインストール
    echo "依存パッケージをインストールしています..."
    pip install --upgrade pip
    pip install -r requirements.txt

    if [ $? -ne 0 ]; then
        echo "✗ 依存パッケージのインストールに失敗しました"
        exit 1
    fi
    echo "✓ 依存パッケージのインストールが完了しました"
    echo ""
    echo "========================================="
    echo "  セットアップが完了しました！"
    echo "========================================="
    echo ""
else
    # 仮想環境を有効化
    echo "仮想環境を有効化しています..."
    source venv/bin/activate
    echo "✓ 仮想環境が有効化されました"
    echo ""

    # 依存パッケージのバージョンチェック
    echo "依存パッケージのバージョンを確認しています..."

    # requirements.txtに記載されている各パッケージをチェック
    needs_update=false
    while IFS= read -r line; do
        # コメント行や空行をスキップ
        if [[ "$line" =~ ^#.*$ ]] || [[ -z "$line" ]]; then
            continue
        fi

        # パッケージ名とバージョンを分離
        package=$(echo "$line" | cut -d'=' -f1)
        required_version=$(echo "$line" | cut -d'=' -f3)

        # インストール済みバージョンを取得
        installed_version=$(pip show "$package" 2>/dev/null | grep "^Version:" | cut -d' ' -f2)

        # パッケージが未インストールまたはバージョンが異なる場合
        if [ -z "$installed_version" ] || [ "$installed_version" != "$required_version" ]; then
            needs_update=true
            break
        fi
    done < requirements.txt

    if [ "$needs_update" = true ]; then
        echo "⚠️  依存パッケージに更新があります"
        echo "パッケージを更新しています..."
        pip install -r requirements.txt

        if [ $? -ne 0 ]; then
            echo "✗ パッケージの更新に失敗しました"
            exit 1
        fi
        echo "✓ パッケージの更新が完了しました"
        echo ""
    else
        echo "✓ すべてのパッケージは最新です"
        echo ""
    fi
fi

# アプリケーションを起動
echo "アプリケーションを起動しています..."
python gui.py
