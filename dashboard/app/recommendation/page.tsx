import { Suspense } from "react";
import { RecommendationView } from "@/components/RecommendationView";
import { Loading } from "@/components/Status";

export default function Page() {
  return <Suspense fallback={<Loading />}><RecommendationView /></Suspense>;
}
