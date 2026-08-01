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

## Threshold calibration protocol

Streams are assigned deterministically at topic level: REFERENCE streams build
known prototypes only; CALIBRATION streams evaluate caller-supplied threshold
configurations and form a Pareto frontier; TEST streams remain untouched until
frozen-configuration evaluation. This prevents temporal leakage within a topic.
Held-out unseen classes may occur in CALIBRATION and TEST, never REFERENCE.

The frontier maximizes known Macro-F1, UNKNOWN precision, and UNKNOWN recall,
while minimizing false-unknown rate. It has no weighted objective, no automatic
best configuration, and no test-set tuning; threshold values are experimental
configuration rather than universal defaults.

## Frozen TEST execution

REFERENCE streams construct prototypes, CALIBRATION streams are used only for
threshold calibration, then a caller freezes a decision configuration before
TEST execution. The final executor compares key-only, schema-only, static
multi-view, temporal multi-view, and open-world multi-view variants without
tuning on TEST or claiming a universally superior variant. Discovery metrics
remain separate planned work.

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

## CALIBRATION RESULTS — NOT FINAL TEST RESULTS

The first reproducible calibration run used `STEmbeddingModel` with
`BAAI/bge-small-en-v1.5` on CPU. Its 384-dimensional embeddings were normalized
by the existing model implementation. Six REFERENCE streams built known-class
prototypes; seven CALIBRATION streams supplied 16 known and 2 unseen
observations. TEST data was not executed or inspected.

The run evaluated 13,872 valid caller-domain configurations and retained 40
Pareto-frontier configurations. The JSON artifact at
`docs/results/semantic_calibration_frontier.json` is authoritative and retains
full floating-point precision. The compact table below rounds thresholds to six
decimals and metrics to three decimals.

| # | Votes | Known sim. | Margin | Unknown sim. | Acc. | Macro-F1 | U-Prec. | U-Recall | False-U |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0.695180 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 2 | 1 | 0.695180 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 3 | 1 | 0.695180 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 4 | 1 | 0.695180 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 5 | 1 | 0.901875 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 6 | 1 | 0.901875 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 7 | 1 | 0.901875 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 8 | 1 | 0.901875 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 9 | 2 | 0.695180 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 10 | 2 | 0.695180 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 11 | 2 | 0.695180 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 12 | 2 | 0.695180 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 13 | 2 | 0.901875 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 14 | 2 | 0.901875 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 15 | 2 | 0.901875 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 16 | 2 | 0.901875 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 17 | 3 | 0.695180 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 18 | 3 | 0.695180 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 19 | 3 | 0.695180 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 20 | 3 | 0.695180 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 21 | 3 | 0.901875 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 22 | 3 | 0.901875 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 23 | 3 | 0.901875 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 24 | 3 | 0.901875 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 25 | 4 | 0.695180 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 26 | 4 | 0.695180 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 27 | 4 | 0.695180 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 28 | 4 | 0.695180 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 29 | 4 | 0.901875 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 30 | 4 | 0.901875 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 31 | 4 | 0.901875 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 32 | 4 | 0.901875 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 33 | 5 | 0.695180 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 34 | 5 | 0.695180 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 35 | 5 | 0.695180 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 36 | 5 | 0.695180 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 37 | 5 | 0.901875 | 0.000000 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 38 | 5 | 0.901875 | 0.017651 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 39 | 5 | 0.901875 | 0.021553 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| 40 | 5 | 0.901875 | 0.168002 | 0.695180 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |

No configuration is declared universally best. No weighted aggregate objective
was used. The frontier exposes operational threshold choices that are
Pareto-equivalent on this calibration split. A configuration must be frozen
under an explicit operational criterion before separate TEST execution.
