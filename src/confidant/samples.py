"""Synthetic demo vault.

All personal details here are invented. They are shaped like the real thing —
a residence card, a resident record, a clinic note, a contract — because the
demo has to show the system handling the documents people actually own, not a
tidy benchmark corpus.

There is one planted contradiction between `residence_card` and
`resident_record`: the registered address differs from the card. That is a
genuinely common renewal problem in Japan, and it is cross-document, so only a
system that reads more than one document at a time can find it.
"""

from __future__ import annotations

from pathlib import Path

SAMPLES: dict[str, dict[str, str]] = {
    "residence_card": {
        "title": "在留カード (Residence Card) — synthetic",
        "text": """在留カード / RESIDENCE CARD (SYNTHETIC — NOT A REAL DOCUMENT)

氏名  山田 太郎
国籍  フィリピン
生年月日  1990-04-12
在留資格  技術・人文知識・国際業務
在留期間  5年
在留期限  2027年3月15日
就労制限  なし
許可類型  就労資格
住居地  東京都港区芝浦4丁目2番8号
在留カード番号  AB12345678CD
交付年月日  2024年3月20日
出入国在留管理庁

備考: 現住所は2025年11月に渋谷区へ転居済み。在留カードの住居地届出は未実施。
""",
    },
    "resident_record": {
        "title": "住民票の写し (Resident Record) — synthetic",
        "text": """住民票の写し (SYNTHETIC)

世帯主  山田 太郎
住所  東京都渋谷区道玄坂1丁目5番3号 メゾン道玄坂 402
氏名  山田 太郎
生年月日  1990年4月12日
世帯構成  本人、配偶者、子1名
住民となった年月日  2025年11月2日
マイナンバー  1234 5678 9012

発行  渋谷区役所
""",
    },
    "clinic_note": {
        "title": "診療記録 (Clinic note) — synthetic",
        "text": """診療記録 (SYNTHETIC)

患者  山田 太郎
受診日  2026年9月14日
主訴  腰痛、睡眠障害
診断  腰椎椎間板ヘルニア（疑い）、不眠
処方  ロキソプロフェン 60mg 1日3回
次回予約  2026年10月26日

電話  03-5555-0123
担当  佐藤 先生
""",
    },
    "employment_contract": {
        "title": "雇用契約書 (Employment contract) — synthetic",
        "text": """雇用契約書 (SYNTHETIC)

雇用主  株式会社ナカムラテック
労働者  山田 太郎
契約期間  2025年4月1日 〜 2027年1月31日
職務  ソフトウェアエンジニア
給与  月額 480,000円（みなし残業40時間を含む）
勤務地  東京都千代田区
更新  契約満了時に双方合意のうえ更新する

連絡先  hr@nakamura-tech.example
""",
    },
    "grocery_note": {
        "title": "買い物メモ (Grocery note)",
        "text": """買い物メモ
- パスタ
- オリーブオイル
- パルミジャーノ
- コーヒー豆（中挽き）
メモ: 土曜は表参道の店が混むので朝に行く。
""",
    },
    "public_article": {
        "title": "AI エージェントの安全性 (public note)",
        "text": """Open agents need out-of-process policy enforcement.

A prompt is not a control. If the guardrail lives in the same process as the
agent, a compromised or merely creative agent can talk its way past it. The
enforcement point has to sit outside the thing being enforced — which is what
NVIDIA OpenShell does with a sandbox, a policy engine and a privacy router.

Confidant applies the same principle to personal documents: the routing
decision is made before the model is loaded, and recorded afterwards.
""",
    },
}

#: Question pairs used by the demo and the test suite.
DEMO_QUESTIONS = {
    "contradiction": "Does anything across my documents put my visa renewal at risk?",
    "local_only": "Summarise what my clinic note says.",
    "web": "What is the current fee for extending a 技術・人文知識・国際業務 visa?",
    "grocery": "What do I need from the shop?",
}


def seed(directory: Path) -> list[Path]:
    """Write the synthetic vault to disk so ingestion is a real file operation."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for doc_id, doc in SAMPLES.items():
        path = directory / f"{doc_id}.txt"
        path.write_text(f"# {doc['title']}\n\n{doc['text']}", encoding="utf-8")
        written.append(path)
    return written
