import { Suspense } from "react";
import { IssueView } from "@/components/IssueView";
import { Loading } from "@/components/Status";

export default function Page() {
  return <Suspense fallback={<Loading />}><IssueView /></Suspense>;
}
