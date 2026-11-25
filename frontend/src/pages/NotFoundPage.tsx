import { Link } from "react-router-dom";
import { usePageTitle } from "../usePageTitle";

export default function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <p>The page you are looking for does not exist.</p>
      <p>
        <Link to="/">Go to the home page</Link>
      </p>
    </>
  );
}
