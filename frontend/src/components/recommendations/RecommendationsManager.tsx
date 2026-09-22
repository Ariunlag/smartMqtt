import RecommendationsPanel from "./RecommendationsPanel";
import { useRecommendationSource } from "./useRecommendationSource";

export default function RecommendationsManager() {
  return <RecommendationsPanel source={useRecommendationSource()} />;
}
