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

## Implemented runner and metrics

The deterministic runner supports key-only, schema-only, static multi-view,
temporal multi-view, and open-world multi-view variants. Open-world runs require
caller-supplied decision thresholds. Known-class metrics include all known
observations: UNKNOWN and UNCERTAIN therefore count as incorrect. UNKNOWN is
positive only for held-out classes; zero denominators return `0.0`.

Implemented metrics are Top-1 accuracy, macro-F1, UNKNOWN precision, UNKNOWN
recall, false-unknown rate, semantic refresh count, and false refresh count.
ARI, NMI, and other discovery metrics remain planned because discovery is not
run by this experiment runner.
