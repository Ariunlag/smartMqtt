# SmartMQTT Semantic Evaluation

## Research question

Does temporal stability-aware multi-view open-world semantic organization
improve behavior compared with simpler static/closed-world baselines?

The controlled semantic benchmark provides deterministic structured stream
observations and explicit ground truth for this research question. It does not
run models, semantic services, metrics, or production workflows.

## Planned comparison families

1. Static single representation
2. Static six-view consensus
3. Temporal/stability-aware six-view consensus
4. Full open-world workflow

## Planned metric families

Known-class metrics:

- Top-1 accuracy
- Macro-F1
- Recall@K
- MRR

Open-world metrics:

- UNKNOWN precision
- UNKNOWN recall
- False-unknown rate

Temporal metrics:

- Class consistency under benign drift
- False semantic refresh rate
- Change response delay

Discovery metrics:

- ARI
- NMI
- Cluster purity/noise behavior

System metrics:

- Embedding refresh count
- Latency
- Computational cost

No experiment runner or metric implementation is included yet.
