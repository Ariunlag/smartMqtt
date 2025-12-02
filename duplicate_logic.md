# ============================================================
# DUPLICATE DETECTION PIPELINE (WITH COMPARISON DETAIL)
# ============================================================

# 1️⃣ NEW TOPIC ARRIVAL
# ------------------------------------------------------------
# A new MQTT message arrives:
#   → topic = "building1/floor2/temp_sensor_A"
#   → payload = { "value": 23.4, "unit": "C" }
# The system:
#   - extracts topic, tags, and timestamp
#   - writes value into InfluxDB
#   - generates a semantic embedding for the topic name and tags
#   - stores the embedding in embedding_store.json
#   - schedules a duplicate check via DupeManager

# 2️⃣ DUPLICATE CHECK INITIALIZATION
# ------------------------------------------------------------
# DupeManager receives the topic and its embedding.
# Instead of checking immediately, it waits DUPE_CHECK_DELAY seconds
# (for example, 120s) to allow other topics to be embedded.

# After delay:
#   - retrieves all stored topics and embeddings
#   - begins comparison phase

# 3️⃣ EMBEDDING COMPARISON LOOP
# ------------------------------------------------------------
# for each existing record in embedding_store:
#     current_topic = record["topic"]
#     if current_topic == new_topic:
#         skip  # avoid comparing topic to itself

#     compute hybrid similarity score between:
#         (new_topic, new_embedding) and (current_topic, record["embedding"])

#     if score ≥ ID_THRESHOLD:
#         mark as potential duplicate
#         record pair in duplicate_store
#         broadcast to frontend via WebSocket
#         stop further comparisons for this topic
#         break

# if loop finishes without match:
#     log: "no duplicates found after checking all topics"

# 4️⃣ HYBRID SIMILARITY CALCULATION
# ------------------------------------------------------------
# Each comparison uses both semantic and numeric signals.

# cosine_similarity = dot(embedding_A, embedding_B) / (||A|| * ||B||)
# → captures linguistic similarity between topic names and tags.

# Fetch last N numeric readings from InfluxDB for both topics.
#   values_A = last 100 readings from topic A
#   values_B = last 100 readings from topic B

# if both series have enough numeric points (≥ MIN_POINTS):
#     compute Pearson correlation r between A and B value sequences
#     convert correlation to [0, 1] scale:
#         corr_score = (r + 1) / 2
#     compute blending weight based on number of shared points:
#         weight = min(1.0, N / 100)
#     hybrid_score = (1 - weight)*cosine_similarity + weight*corr_score
# else:
#     hybrid_score = cosine_similarity  # fallback if insufficient data

# return hybrid_score to the comparison loop

# 5️⃣ DUPLICATE DETECTION DECISION
# ------------------------------------------------------------
# if hybrid_score ≥ 0.9:
#     create record in duplicate_store.json:
#         {
#           "topics": [topic_A, topic_B],
#           "score": hybrid_score,
#           "status": "PENDING"
#         }
#     notify frontend:
#         event_type = "duplicate"
#         data = record
#     (the loop breaks; only first strong match triggers)

# if hybrid_score < 0.9 for all topics:
#     no record created, continue monitoring new topics

# 6️⃣ USER CONFIRMATION (FRONTEND)
# ------------------------------------------------------------
# In UI, user sees:
#     Duplicate detected: topic_A ↔ topic_B (score 0.92)
# User clicks:
#     "Approve" → confirms as duplicate
#     "Reject" → marks as not duplicate

# Corresponding API call:
# POST /confirm-duplicate
# {
#   "topicA": topic_A,
#   "topicB": topic_B,
#   "action": "approve" or "delete"
# }

# 7️⃣ CONFIRMATION HANDLING
# ------------------------------------------------------------
# Backend receives the action:
#   if action == "approve":
#       mark status = "CONFIRMED_DUPLICATE"
#       unsubscribe topic_B from MQTT (keep only one active)
#   if action == "delete":
#       mark status = "NOT_DUPLICATE"
# update duplicate_store.json
# broadcast refresh event via WebSocket

# 8️⃣ CONTINUOUS LOOP
# ------------------------------------------------------------
# The process repeats for every new topic.
# The system continually maintains and updates the duplicate store,
# ensuring no redundant data streams remain active.
