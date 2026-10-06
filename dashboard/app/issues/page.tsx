import { Suspense } from "react";
import { IssuesView } from "@/components/IssuesView";
import { Loading } from "@/components/Status";

export default function Page() {
  return <Suspense fallback={<Loading />}><IssuesView /></Suspense>;
}
