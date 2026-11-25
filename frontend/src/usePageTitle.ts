import { useEffect } from "react";

const APP_NAME = "FindMyThing";

/** Set the document title for the current page (screen-reader and tab context on client-side navigation). */
export function usePageTitle(title: string | null): void {
  useEffect(() => {
    document.title = title === null ? APP_NAME : `${title} - ${APP_NAME}`;
  }, [title]);
}
