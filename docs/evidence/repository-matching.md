# 论文与代码仓库匹配

这套小型回归集用论文或作者页面逐项核对 4 篇论文和 6 个候选仓库。脚本对固定候选运行当前评分器和 Code Agent 默认的 0.7 选择门槛。

| 案例 | 预期选择 | 标注依据 |
| --- | --- | --- |
| DropEdge | `DropEdge/DropEdge` | 论文声明代码地址，仓库描述与论文标题对应。[论文](https://arxiv.org/abs/1907.10903) · [仓库](https://github.com/DropEdge/DropEdge) |
| SPIRAL 与 TSB-AD | `Smendowski/SPIRAL` | 论文的代码可用性声明指定 SPIRAL，TSB-AD 是论文引用的数据集与评测基准。[论文](https://link.springer.com/article/10.1007/s10994-026-07134-7) |
| PLOS 论文页的通用链接 | 放弃选择当前候选 | 页面导航指向出版社的主题词表。[论文页](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0134254) · [词表仓库](https://github.com/PLOS/plos-thesaurus) |
| Graph Attention Networks | `PetarV-/GAT` | 作者页面链接到原实现，项目 README 列出独立的 PyTorch 移植版。[作者页面](https://petar-v.com/GAT/) · [作者仓库](https://github.com/PetarV-/GAT) · [独立移植](https://github.com/diegoantognini/pyGAT) |

本次 4 个案例的选择结果均符合标注，3 个负候选中有 0 个被归为作者或官方实现。放弃选择仅针对该案例提供的候选集合。结果只覆盖固定输入上的评分行为，在线候选发现质量、未知论文的准确率和论文复现质量需要单独验证。

```bash
uv run python scripts/evaluate_repository_matches.py
```

[固定候选与预期结果](../../eval/repository-matches.json) · [评分实现](../../src/module_agent/code/application/scoring.py)
