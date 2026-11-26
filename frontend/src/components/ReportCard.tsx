import { Link } from "react-router-dom";
import type { Report } from "../api/data";
import styles from "./Page.module.css";
import { StatusBadge } from "./ui";

/** One report in a results grid (Browse, My reports): type rubric, title, excerpt, meta line and status chip. */
export default function ReportCard({ report: r }: { report: Report }) {
  return (
    <li className={styles["card"]}>
      <p className={styles["rubric"]}>
        {r.report_type === "LOST" ? "Lost" : "Found"}
        {r.has_photo ? " \u00b7 Photo" : ""}
      </p>
      <h2>
        <Link to={`/reports/${r.report_id}`}>{r.title}</Link>
      </h2>
      {r.description ? <p className={styles["excerpt"]}>{r.description}</p> : null}
      <p className={styles["meta"]}>
        {r.category.name} {"\u00b7"} {r.location.name} {"\u00b7"} {r.occurred_on}
      </p>
      <div className={styles["cardFoot"]}>
        <StatusBadge status={r.status} />
      </div>
    </li>
  );
}
