import type { RouteObject } from "react-router-dom";
import Layout from "./components/Layout";
import RequireRole from "./components/RequireRole";
import HomePage from "./pages/HomePage";
import NotFoundPage from "./pages/NotFoundPage";
import SignInPage from "./pages/SignInPage";
import RegisterPage from "./pages/RegisterPage";
import ItemSearchPage from "./pages/ItemSearchPage";
import ReportFormPage from "./pages/ReportFormPage";
import ReportDetailPage from "./pages/ReportDetailPage";
import MyReportsPage from "./pages/MyReportsPage";
import MyClaimsPage from "./pages/MyClaimsPage";
import ClaimDetailPage from "./pages/ClaimDetailPage";
import ModeratorClaimsPage from "./pages/moderator/ModeratorClaimsPage";
import ModeratorClaimDetailPage from "./pages/moderator/ModeratorClaimDetailPage";
import ModeratorAnalyticsPage from "./pages/moderator/ModeratorAnalyticsPage";
import ModeratorActivityPage from "./pages/moderator/ModeratorActivityPage";

/**
 * Route table, kept separate from the browser router so tests can mount it in a memory router.
 * Routing is presentation only: the backend stays authoritative for authentication and authorization.
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      // Public / Anonymous accessible
      { index: true, element: <HomePage /> },
      { path: "sign-in", element: <SignInPage /> },
      { path: "register", element: <RegisterPage /> },
      { path: "reports", element: <ItemSearchPage /> },
      { path: "reports/:reportId", element: <ReportDetailPage /> },

      // Student-protected workflows
      {
        element: <RequireRole role="STUDENT" />,
        children: [
          { path: "reports/new", element: <ReportFormPage /> },
          { path: "my/reports", element: <MyReportsPage /> },
          { path: "my/claims", element: <MyClaimsPage /> },
          { path: "my/claims/:claimId", element: <ClaimDetailPage /> },
        ],
      },

      // Moderator-protected workflows
      {
        path: "moderator",
        element: <RequireRole role="MODERATOR" />,
        children: [
          { index: true, element: <ModeratorClaimsPage /> },
          { path: "claims/:claimId", element: <ModeratorClaimDetailPage /> },
          { path: "analytics", element: <ModeratorAnalyticsPage /> },
          { path: "activity", element: <ModeratorActivityPage /> },
        ],
      },

      // Fallback
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
