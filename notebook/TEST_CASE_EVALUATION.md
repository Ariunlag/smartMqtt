# Class Recommendation Test Case Evaluation

## Evaluation setup

- Dataset: 29 streams, 6 labels, 4–6 streams per label.
- Model: `BAAI/bge-small-en-v1.5` (the backend default).
- Validation: leave-one-manufacturer-out class recommendation.
- Metrics: Top-1 accuracy, Macro-F1, Recall@3, and MRR.
- Flat methods use class-centroid cosine similarity.
- Pair methods use one-to-one Hungarian field matching and mean similarity to
  training streams in each class.

The results are exploratory because the dataset is small and synthetic.

## Results

### Flat payload representations

| Method | Top-1 | Macro-F1 | Recall@3 | MRR |
|---|---:|---:|---:|---:|
| key only | 0.724 | 0.728 | 0.828 | 0.798 |
| field schema | 0.690 | 0.693 | 0.862 | 0.797 |
| key:value | 0.552 | 0.517 | 0.931 | 0.740 |
| numeric key only | 0.517 | 0.483 | 0.931 | 0.728 |
| value only | 0.310 | 0.320 | 0.759 | 0.561 |

`key only` is the strongest Top-1 method on this dataset. `key:value` has lower
Top-1 accuracy but much better Recall@3, indicating that values add ambiguity
while often keeping the correct class somewhere in the shortlist.

### Pair-level representations

| Method | Top-1 | Macro-F1 | Recall@3 | MRR |
|---|---:|---:|---:|---:|
| key:value without numeric values | 0.517 | 0.502 | 0.759 | 0.682 |
| direct key:value | 0.483 | 0.465 | 0.724 | 0.649 |
| numeric-aware, numeric value weight 0.00 | 0.448 | 0.392 | 0.724 | 0.628 |
| key only | 0.414 | 0.383 | 0.759 | 0.611 |
| weighted key 0.75 / value 0.25 | 0.414 | 0.383 | 0.690 | 0.589 |
| weighted key 0.50 / value 0.50 | 0.414 | 0.367 | 0.655 | 0.584 |
| value only | 0.414 | 0.365 | 0.690 | 0.582 |
| weighted key 0.25 / value 0.75 | 0.379 | 0.332 | 0.621 | 0.561 |

Linear key/value fusion does not improve recommendation on these cases.
Embedding `key:value` as one phrase performs better than independently embedding
the key and value and averaging their vectors.

## Per-class behavior of the best flat method

| Class | Correct | Total | Accuracy |
|---|---:|---:|---:|
| temperature_sensor | 5 | 6 | 0.833 |
| voltage_sensor | 4 | 5 | 0.800 |
| occupancy_sensor | 3 | 5 | 0.600 |
| device_status | 3 | 5 | 0.600 |
| humidity_sensor | 3 | 4 | 0.750 |
| metadata_identity | 3 | 4 | 0.750 |

The difficult cases use short or generic keys:

- `t`, `loc`, and `quality` for temperature;
- `asset_id` and `v_level` for voltage;
- `building_id`, `count`, and `confidence` for occupancy;
- `asset`, `mode`, `equipment`, and `battery` for device status;
- `rh`, `status`, and `sample_rate_sec` for humidity;
- `site`, `gateway`, and `connected_devices` for metadata.

These are useful adversarial examples, but more examples of each alias are
needed before coefficient selection.

## What the test cases do well

- Classes are reasonably balanced.
- Numeric values deliberately overlap across temperature, voltage, and
  occupancy, exposing the weakness of value-only embeddings.
- Keys contain realistic aliases such as `temp`, `temperature_celsius`, `t`,
  `volt`, `v_level`, `rh`, and `moisture_level`.
- Categorical states, nulls, booleans, units, firmware, and sampling metadata
  create useful noise.
- The repeated value `Warehouse_01` under different keys is a good test of
  whether key context matters.

## Test case problems

### 1. The target taxonomy mixes different concepts

`temperature_sensor`, `voltage_sensor`, and `humidity_sensor` describe measured
phenomena. `device_status` describes a message purpose, while
`metadata_identity` describes a record type. A real stream may legitimately be
both a temperature sensor and a device-status stream.

Use either:

- a hierarchical target (`domain`, `measurement_type`, `message_role`); or
- multi-label targets.

### 2. `metadata_identity` is not internally coherent

Three asset-registry records and one gateway summary are assigned the same
class. The gateway case has a different semantic role and is the failure for
the best flat method. Split it into a clearer label or redefine the class as
`infrastructure_metadata` with more representative examples.

### 3. Notebook input does not match production input

The backend embeds `message.tags`, while this dataset contains a single
`payload` object mixing identity metadata and measurement fields. A score from
this dataset therefore does not directly measure the current production tag
grouping behavior.

Represent each message explicitly as:

```json
{
  "topic": "...",
  "tags": {},
  "fields": {},
  "true_labels": {}
}
```

Then evaluate `tags`, field names, topic path, and their combinations as
separate ablations.

### 4. Manufacturer holdout is only a proxy

Manufacturer names are labels in the CSV but do not correspond to clearly
documented vendor-specific schema conventions. The split prevents the same
manufacturer from appearing in training and testing, but it is not yet strong
evidence of cross-vendor generalization.

Add real vendor schemas or generate each vendor from an explicit alias and
payload-template policy.

### 5. There is no unknown or abstention case

The evaluator must always choose one of six classes. Production recommendation
needs out-of-distribution streams and a confidence/margin threshold that can
return `unknown`.

### 6. Coverage is too narrow

Missing cases include:

- nested objects and arrays;
- missing, renamed, and extra fields;
- empty tags;
- unit variants and malformed units;
- multilingual keys;
- spelling errors and abbreviations;
- mixed measurement payloads;
- unseen classes;
- schema drift over time;
- repeated messages from the same stream.

## Recommendation

Keep the current 29 streams as a small adversarial smoke-test suite. Do not use
it to choose a production coefficient. Build a larger dataset with explicit
`tags`/`fields`, hierarchical or multi-label targets, real vendor holdouts, and
unknown cases. On the current evidence, `flat_key_only` is the baseline to beat;
weighted key/value fusion is not justified.
