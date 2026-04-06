# GitHub Copilot SDK ベースのマルチエージェント実装プラン

## 1. 目的

GitHub Copilot SDK を用いて、**要件を受け取り、要件を満たす実装を完成させるマルチエージェント環境**を構築する。  
この環境は単なるコード生成ではなく、以下を一貫して扱う。

- 要件の受領と整理
- 実装計画の作成
- 設計・ドキュメント生成
- コード生成
- テスト生成
- テスト環境構築
- テスト実行
- 結果評価と修正ループ
- セッション継続とコンテキスト保持
- モデル選択の自動最適化

開発自体は `uv` で管理し、Python ベースで実装する。

---

## 2. ゴール

### 2.1 機能ゴール

- オーケストレーターを中心としたマルチエージェント実行基盤を作る
- セッション上限やトークン制約に近づいた際、自動で新セッションへ移行できる
- `persistent` を使って文脈を引き継げる
- タスク種別・難易度に応じてモデルを自動切り替えできる
- 実装からテスト、検証、修正までを閉ループで回せる
- 失敗時に再試行・縮退運転・人間へのエスカレーションができる
- 実行履歴、成果物、判断理由を追跡できる

### 2.2 非機能ゴール

- 再現性
- 可観測性
- 拡張性
- 安全性
- 中断・再開容易性
- コスト制御
- 長時間タスク耐性

---

## 3. ユーザー要件の整理

### 3.1 指定済み要件

1. **セッションの自動管理**
   - トークンリミット接近時に新セッションを自動開始
   - `persistent` を利用してコンテキストを引き継ぐ

2. **マルチエージェント**
   - オーケストレーターが以下のエージェントを統合
     - 実装計画
     - ドキュメント生成
     - コード生成
     - テスト生成
     - テスト環境構築
     - テスト実行

3. **GPT-5.4**
   - デフォルトは GPT-5.4
   - タスク難易度や種別に応じてモデルを自動切り替え

4. **uv**
   - このワークフロー自体の開発は `uv` で管理
   - テストツールは追加済み

### 3.2 追加すべき要件

要件を満たすだけでは不十分なので、実運用に必要な機能を追加する。

#### A. 要件品質の向上

- 要件の曖昧さ検出
- 不足情報の抽出
- 前提条件・制約条件の明文化
- 受け入れ条件の自動生成
- 実装対象外の明示

#### B. 計画品質の向上

- タスク分解
- 依存関係解析
- 並列実行可能タスクの抽出
- リスク評価
- 見積りの粗算出
- ロールバック方針の定義

#### C. 実装品質の向上

- 既存コード調査
- 変更影響範囲分析
- コーディング規約適合
- 既存アーキテクチャ整合性チェック
- 差分最小化方針
- 生成コードの自己レビュー

#### D. テスト品質の向上

- 単体テスト生成
- 結合テスト生成
- 回帰テスト観点生成
- テストデータ準備
- テスト失敗時の原因分類
- flaky test 検知補助

#### E. 運用品質の向上

- 実行ログの構造化
- エージェントごとの成果物保存
- セッション再開時の状態復元
- 途中成果物のスナップショット
- コスト・トークン使用量の記録
- 失敗時の再実行戦略

#### F. 安全性

- 危険操作のガード
- 破壊的変更前の確認フック
- シークレット混入検知
- 外部コマンド実行ポリシー
- ファイル変更対象の allowlist / denylist
- 依存追加時の審査フロー

#### G. 人間との協調

- 要確認事項の明示
- 承認待ちステップの導入
- 実装案の比較提示
- 失敗時の簡潔な報告
- 最終成果物サマリ生成

---

## 4. 想定アーキテクチャ

## 4.1 全体像

システムは以下のレイヤで構成する。

1. **Entry Layer**
   - CLI
   - 将来的には API / Web UI も追加可能

2. **Orchestration Layer**
   - オーケストレーター
   - ワークフロー状態管理
   - セッション管理
   - モデル選択
   - エージェント間ルーティング

3. **Agent Layer**
   - 要件分析エージェント
   - 計画エージェント
   - ドキュメントエージェント
   - 実装エージェント
   - テスト設計エージェント
   - テスト環境エージェント
   - テスト実行エージェント
   - レビューエージェント
   - 修正エージェント

4. **Execution Layer**
   - リポジトリ読取
   - ファイル編集
   - テスト実行
   - 静的解析
   - フォーマット
   - セキュリティチェック

5. **Persistence Layer**
   - Copilot SDK の `persistent`
   - ローカル成果物保存
   - 実行ログ
   - 状態スナップショット

---

## 5. エージェント構成

## 5.1 オーケストレーター

責務:

- ユーザー要求の受理
- ワークフロー初期化
- タスク分解
- 各エージェントへの委譲
- 実行順序制御
- 並列化制御
- セッション切替制御
- モデル選択
- 成果物統合
- 最終判定

入力:

- ユーザー要件
- リポジトリ状態
- 過去の persistent context
- 実行ポリシー

出力:

- 実行計画
- 各エージェントへのタスク
- 最終成果物サマリ
- 完了/失敗ステータス

## 5.2 要件分析エージェント

責務:

- 要件の構造化
- 曖昧点抽出
- 制約抽出
- 受け入れ条件生成
- 実装対象/対象外の整理

成果物:

- `requirements.normalized.md`
- `acceptance-criteria.md`
- `open-questions.md`

## 5.3 計画エージェント

責務:

- 実装計画作成
- タスク分解
- 依存関係整理
- 並列化候補抽出
- リスク整理

成果物:

- `implementation-plan.md`
- `task-breakdown.md`
- `risk-register.md`

## 5.4 ドキュメントエージェント

責務:

- 設計文書作成
- ADR 作成
- README 更新案作成
- 運用手順書作成

成果物:

- `design.md`
- `adr/*.md`
- `runbook.md`

## 5.5 実装エージェント

責務:

- コード生成
- 既存コードへの差分適用
- 小さな単位での変更
- 実装根拠の記録

成果物:

- ソースコード差分
- 実装メモ

## 5.6 テスト設計エージェント

責務:

- テスト観点抽出
- 単体/結合/回帰テスト設計
- 境界値・異常系洗い出し

成果物:

- `test-plan.md`
- テストケース一覧

## 5.7 テスト環境エージェント

責務:

- テスト実行前提の確認
- 必要な設定・fixture・mock 構築
- `uv` ベースの実行手順整備

成果物:

- テスト設定差分
- 実行手順

## 5.8 テスト実行エージェント

責務:

- テスト実行
- 結果収集
- 失敗分類
- 再現手順整理

成果物:

- `test-results.md`
- 失敗サマリ
- ログ要約

## 5.9 レビューエージェント

責務:

- 実装レビュー
- 設計整合性確認
- セキュリティ・保守性観点レビュー
- テスト不足指摘

成果物:

- `review-report.md`

## 5.10 修正エージェント

責務:

- レビュー指摘やテスト失敗に基づく修正
- 再実行判断
- 収束判定補助

---

## 6. ワークフロー設計

## 6.1 標準フロー

1. 要件受領
2. 要件正規化
3. 不足情報抽出
4. 実装計画作成
5. 設計/ドキュメント生成
6. 実装
7. テスト設計
8. テスト環境整備
9. テスト実行
10. レビュー
11. 修正
12. 再テスト
13. 完了判定
14. 成果物サマリ出力

## 6.2 反復ループ

以下の条件でループする。

- テスト失敗
- レビュー指摘あり
- 受け入れ条件未達
- 静的解析エラー
- セキュリティチェック失敗

ループ上限を設ける。

- 軽微修正ループ: 3 回
- 大規模再計画ループ: 1 回
- それ以上は人間へエスカレーション

## 6.3 並列化方針

並列化可能な例:

- ドキュメント生成とテスト観点抽出
- 実装対象ごとの独立タスク
- 複数テストスイートの実行
- レビュー観点の分割

並列化しない例:

- 依存関係が未解決の実装
- 破壊的変更を含むタスク
- 同一ファイル競合が高い変更

---

## 7. セッション自動管理設計

## 7.1 背景

長い実装タスクでは、1 セッション内で全履歴を保持し続けるのは難しい。  
そのため、**セッションをまたいでも作業継続できる設計**を最初から組み込む。

## 7.2 必要機能

- トークン使用量の監視
- 閾値到達前の事前退避
- `persistent` への状態保存
- 新セッション起動
- 復元プロンプト生成
- 未完了タスクの再投入
- セッションチェーン管理

## 7.3 保存すべきコンテキスト

- ユーザー要求の正規化結果
- 現在の計画
- 完了済みタスク
- 未完了タスク
- 失敗履歴
- 重要な設計判断
- 変更済みファイル一覧
- テスト結果要約
- 次に行うべきアクション
- モデル選択履歴

## 7.4 セッション切替トリガー

- 推定トークン使用率が閾値超過
- 長時間実行
- コンテキスト肥大化
- 重要マイルストーン到達
- 大きなフェーズ遷移前

## 7.5 セッション再開時の復元プロンプト

復元時には以下を含める。

- 現在の目的
- 完了済み事項
- 未完了事項
- 直近の失敗
- 制約条件
- 次アクション
- 参照すべき成果物

---

## 8. モデル選択戦略

## 8.1 基本方針

- デフォルトは **GPT-5.4**
- タスクの性質に応じて自動切替
- 品質優先とコスト優先のモードを持つ

## 8.2 タスク別の選択例

### 高難度・設計判断系
- 要件分析
- アーキテクチャ設計
- 複雑なバグ修正
- レビュー

→ 高性能モデルを優先

### 中難度・生成系
- 実装コード生成
- テスト生成
- ドキュメント生成

→ デフォルトモデルまたは中コストモデル

### 低難度・定型処理系
- 要約
- ログ整理
- 実行結果整形
- 定型ドキュメント更新

→ 軽量モデルを優先

## 8.3 モデルルータに必要な入力

- タスク種別
- 推定難易度
- 必要精度
- 許容レイテンシ
- コスト上限
- 失敗回数
- コンテキスト長

## 8.4 フォールバック

- 主モデル失敗時の代替モデル
- タイムアウト時の再試行モデル
- 低コスト縮退モード
- 人間確認モード

---

## 9. 状態管理設計

## 9.1 管理すべき状態

- workflow id
- session id
- parent session id
- current phase
- task queue
- in-progress tasks
- completed tasks
- blocked tasks
- artifacts
- changed files
- test status
- review status
- retry counters
- escalation flags

## 9.2 状態遷移

主要状態:

- `initialized`
- `requirements_analyzed`
- `planned`
- `design_generated`
- `implementing`
- `testing`
- `reviewing`
- `fixing`
- `completed`
- `failed`
- `needs_human_input`

## 9.3 永続化単位

- ワークフロー全体状態
- エージェントごとの中間成果物
- セッション切替時スナップショット
- 実行ログ
- 最終サマリ

---

## 10. 成果物設計

最低限、以下の成果物を残す。

- `docs/requirements.normalized.md`
- `docs/acceptance-criteria.md`
- `docs/open-questions.md`
- `docs/implementation-plan.md`
- `docs/task-breakdown.md`
- `docs/risk-register.md`
- `docs/design.md`
- `docs/test-plan.md`
- `docs/test-results.md`
- `docs/review-report.md`
- `docs/final-summary.md`

補助的に以下も有用。

- `artifacts/workflow-state.json`
- `artifacts/session-snapshot.json`
- `artifacts/model-routing-log.json`
- `artifacts/execution-log.jsonl`

---

## 11. リポジトリ構成案

```/dev/null/devagents-tree.txt#L1-31
devagents/
├─ docs/
│  ├─ implementation-plan.md
│  ├─ requirements.normalized.md
│  ├─ acceptance-criteria.md
│  ├─ open-questions.md
│  ├─ task-breakdown.md
│  ├─ risk-register.md
│  ├─ design.md
│  ├─ test-plan.md
│  ├─ test-results.md
│  ├─ review-report.md
│  └─ final-summary.md
├─ artifacts/
│  ├─ workflow-state.json
│  ├─ session-snapshot.json
│  ├─ model-routing-log.json
│  └─ execution-log.jsonl
├─ src/
│  └─ devagents/
│     ├─ __init__.py
│     ├─ main.py
│     ├─ config.py
│     ├─ models/
│     │  ├─ routing.py
│     │  └─ policies.py
│     ├─ orchestration/
│     │  ├─ orchestrator.py
│     │  ├─ workflow.py
│     │  ├─ session_manager.py
│     │  ├─ state_store.py
│     │  └─ task_graph.py
│     ├─ agents/
│     │  ├─ base.py
│     │  ├─ requirements.py
│     │  ├─ planner.py
│     │  ├─ documentation.py
│     │  ├─ implementation.py
│     │  ├─ test_design.py
│     │  ├─ test_env.py
│     │  ├─ test_runner.py
│     │  ├─ reviewer.py
│     │  └─ fixer.py
│     └─ runtime/
│        ├─ artifacts.py
│        ├─ logging.py
│        └─ policies.py
```

---

## 12. Python パッケージ設計方針

## 12.1 基本方針

- Python 3.14 前提
- `uv` で依存管理
- SDK 依存は `github-copilot-sdk`
- テストは `pytest`
- 静的品質は `ruff`
- セキュリティ確認は `bandit`

## 12.2 実装スタイル

- dataclass / typed model を多用
- 状態は明示的に持つ
- エージェント I/O を構造化
- 文字列ベースではなく、可能な限り schema 化
- ログは JSON Lines を優先

---

## 13. コンポーネント別実装方針

## 13.1 `session_manager.py`

責務:

- セッション開始
- セッション継続
- トークン使用量推定
- 閾値判定
- `persistent` 保存/復元
- セッションチェーン管理

必要 API:

- `start_session()`
- `should_rotate_session()`
- `snapshot_context()`
- `restore_context()`
- `rotate_session()`

## 13.2 `orchestrator.py`

責務:

- ワークフロー起動
- フェーズ遷移
- エージェント呼び出し
- エラー処理
- 再試行制御
- 最終判定

必要 API:

- `run(requirement: str)`
- `dispatch(task)`
- `collect_results()`
- `handle_failure()`
- `finalize()`

## 13.3 `workflow.py`

責務:

- 状態遷移管理
- タスクキュー管理
- 完了判定
- ブロッカー管理

## 13.4 `routing.py`

責務:

- モデル選択
- タスク分類
- コスト/品質ポリシー適用
- フォールバック選択

## 13.5 `state_store.py`

責務:

- ワークフロー状態の永続化
- スナップショット保存
- 復元
- 成果物インデックス管理

---

## 14. エージェント共通インターフェース案

```/dev/null/agent-interface.py#L1-31
from dataclasses import dataclass
from typing import Any

@dataclass
class AgentTask:
    name: str
    objective: str
    inputs: dict[str, Any]
    constraints: dict[str, Any]

@dataclass
class AgentResult:
    status: str
    summary: str
    outputs: dict[str, Any]
    artifacts: list[str]
    next_actions: list[str]
    risks: list[str]

class BaseAgent:
    agent_name: str

    async def run(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError
```

---

## 15. オーケストレーターの制御ロジック案

```/dev/null/orchestrator-flow.py#L1-42
async def run_workflow(requirement: str) -> WorkflowResult:
    state = workflow.initialize(requirement)

    req_result = await requirements_agent.run(...)
    state.apply(req_result)

    plan_result = await planner_agent.run(...)
    state.apply(plan_result)

    if state.has_open_questions():
        state.mark_needs_human_input()
        return state.to_result()

    doc_result = await documentation_agent.run(...)
    test_plan_result = await test_design_agent.run(...)

    impl_result = await implementation_agent.run(...)
    state.apply(impl_result)

    env_result = await test_env_agent.run(...)
    state.apply(env_result)

    test_result = await test_runner_agent.run(...)
    state.apply(test_result)

    review_result = await reviewer_agent.run(...)
    state.apply(review_result)

    while state.needs_fix_loop():
        fix_result = await fixer_agent.run(...)
        state.apply(fix_result)

        test_result = await test_runner_agent.run(...)
        state.apply(test_result)

        review_result = await reviewer_agent.run(...)
        state.apply(review_result)

    return state.finalize()
```

---

## 16. 追加で必須と考える運用要件

## 16.1 受け入れ条件駆動

実装完了判定は「コードが生成されたか」ではなく、以下で判定する。

- 受け入れ条件を満たしたか
- テストが通ったか
- レビューで重大指摘がないか
- ドキュメントが更新されたか
- 未解決事項が明示されたか

## 16.2 変更影響の可視化

各変更について以下を残す。

- 変更対象ファイル
- 変更理由
- 影響範囲
- テスト対象
- ロールバック方法

## 16.3 失敗分類

失敗は最低限以下に分類する。

- 要件不明
- 設計不整合
- 実装失敗
- テスト環境不備
- テスト失敗
- モデル出力不安定
- 外部依存失敗
- 権限/安全ポリシー違反

## 16.4 人間確認ポイント

以下は承認フック候補。

- 大規模リファクタ
- 依存追加
- 破壊的変更
- データ移行
- セキュリティ影響あり
- 要件解釈に複数案ある場合

---

## 17. 実装フェーズ計画

## Phase 1: 基盤整備

目的:

- 最小限のワークフロー骨格を作る

実装項目:

- `uv` ベースの開発環境確認
- 基本パッケージ構成作成
- `BaseAgent` 実装
- `WorkflowState` 実装
- `Orchestrator` 骨格実装
- ローカル成果物保存機構
- CLI エントリポイント

完了条件:

- 単一要求を受けて、要件分析→計画生成まで動く

## Phase 2: セッション管理

目的:

- 長時間タスク継続を可能にする

実装項目:

- セッション監視
- `persistent` 保存/復元
- セッションローテーション
- スナップショット生成
- 復元プロンプト生成

完了条件:

- セッション切替後も計画と状態を維持して継続できる

## Phase 3: マルチエージェント拡張

目的:

- 実装・テスト・レビューまで閉ループ化する

実装項目:

- 実装エージェント
- テスト設計エージェント
- テスト環境エージェント
- テスト実行エージェント
- レビューエージェント
- 修正エージェント
- 反復ループ制御

完了条件:

- 実装→テスト→修正→再テストが自動で回る

## Phase 4: モデルルーティング

目的:

- タスクに応じたモデル最適化

実装項目:

- タスク分類器
- モデル選択ポリシー
- フォールバック戦略
- コスト/品質モード

完了条件:

- タスク種別に応じてモデル選択が変わる

## Phase 5: 安全性・可観測性

目的:

- 実運用可能な品質にする

実装項目:

- 構造化ログ
- 実行トレース
- 安全ポリシー
- シークレット検知フック
- 変更対象制御
- 失敗レポート整備

完了条件:

- 失敗時の原因追跡と安全制御が可能

## Phase 6: 品質向上

目的:

- 実用性を高める

実装項目:

- 受け入れ条件駆動の完了判定
- 自己レビュー強化
- リスク登録
- 人間承認フロー
- 成果物サマリ自動生成

---

## 18. テスト計画

## 18.1 単体テスト

対象:

- 状態遷移
- モデルルーティング
- セッションローテーション判定
- スナップショット保存/復元
- タスクキュー制御

## 18.2 結合テスト

対象:

- 要件分析→計画生成
- 実装→テスト→修正ループ
- セッション切替を跨ぐ継続
- モデル切替を含む実行

## 18.3 E2E テスト

対象:

- 単純な機能追加要求
- ドキュメント更新要求
- テスト追加要求
- 失敗からの回復シナリオ

## 18.4 非機能テスト

対象:

- 長文要件入力
- 長時間実行
- 大量成果物生成
- セッション切替頻発時の安定性
- コスト上限制御

---

## 19. リスクと対策

| リスク | 内容 | 対策 |
|---|---|---|
| セッション復元不全 | 文脈が欠落して継続不能 | スナップショットを構造化し、次アクションを必須保存 |
| モデル切替品質低下 | 軽量モデルで精度不足 | 高リスクタスクは高性能モデル固定 |
| エージェント間不整合 | 出力形式が揃わない | 共通 schema を定義 |
| 無限修正ループ | テスト失敗が収束しない | ループ回数制限とエスカレーション |
| 破壊的変更 | 意図しない大規模変更 | 安全ポリシーと承認フック |
| コスト増大 | 長時間・多モデル利用 | 予算上限と縮退モード |
| テスト環境依存 | ローカル差異で失敗 | 環境前提チェックと標準実行手順化 |

---

## 20. MVP 定義

最初の実装では、以下に絞る。

### MVP 範囲

- CLI から要件文字列を受け取る
- 要件分析エージェント実行
- 計画エージェント実行
- 実装エージェント実行
- テスト設計/実行エージェント実行
- レビュー/修正ループを 1 回以上回せる
- セッションスナップショット保存
- 閾値ベースのセッション切替
- GPT-5.4 をデフォルト利用
- タスク種別ベースの簡易モデル切替
- `docs/` と `artifacts/` に成果物保存

### MVP で後回しにしてよいもの

- Web UI
- 高度な並列スケジューラ
- 複雑なコスト最適化
- 高度な履歴検索
- 複数リポジトリ同時対応

---

## 21. 実装順の推奨

1. 状態モデル
2. オーケストレーター骨格
3. 要件分析エージェント
4. 計画エージェント
5. 成果物保存
6. 実装エージェント
7. テスト設計/実行
8. 修正ループ
9. セッション管理
10. モデルルーティング
11. 安全ポリシー
12. 可観測性強化

この順にすると、早い段階で「動く縦切り」を作れる。

---

## 22. 完了判定

このプロジェクトの完了条件は以下。

- 要件から実装完了までの一連の流れを自動実行できる
- セッション切替後も継続できる
- `persistent` による文脈保持が機能する
- モデル自動切替が機能する
- テスト生成と実行が組み込まれている
- レビューと修正ループがある
- 成果物が `docs/` と `artifacts/` に保存される
- 失敗時に原因と次アクションを出せる

---

## 23. 次の具体アクション

実装開始時の最初のタスクは以下。

1. `src/devagents/` 配下の基本パッケージ構成を作る
2. `WorkflowState` と `BaseAgent` を定義する
3. `Orchestrator` の最小実装を作る
4. 要件分析エージェントと計画エージェントを先に実装する
5. `docs/` と `artifacts/` への保存機構を作る
6. その後にセッション管理とモデルルーティングを追加する

---