import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthContext, type AuthContextValue } from "./context/auth-context";
import { routes } from "./routes";

function mockAuthValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    state: { status: "anonymous" },
    signIn: async () => ({
      user_id: "test-user-id",
      email: "student@campus.edu",
      display_name: "Test Student",
      role: "STUDENT",
    }),
    register: async () => ({
      user_id: "test-user-id",
      email: "student@campus.edu",
      display_name: "Test Student",
      role: "STUDENT",
    }),
    signOut: async () => {},
    retry: () => {},
    ...overrides,
  };
}

function renderAt(path: string, authValue = mockAuthValue()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AuthContext.Provider value={authValue}>
      <RouterProvider router={router} />
    </AuthContext.Provider>,
  );
  return router;
}

describe("application shell", () => {
  it("renders the home page inside the layout landmarks", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1, name: /campus lost & found/i })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("offers a skip link that targets the main landmark", () => {
    renderAt("/");
    const skip = screen.getByRole("link", { name: /skip to main content/i });
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("sets the document title per page", () => {
    renderAt("/");
    expect(document.title).toBe("FindMyThing");
    renderAt("/sign-in");
    expect(document.title).toBe("Sign in - FindMyThing");
  });
});

describe("routing", () => {
  it("renders the sign-in route", () => {
    renderAt("/sign-in");
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the register route", () => {
    renderAt("/register");
    expect(screen.getByRole("heading", { level: 1, name: "Create account" })).toBeInTheDocument();
  });

  it("renders a not-found page for unknown URLs, keeping the shell and a way home", () => {
    renderAt("/no/such/page");
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to the home page/i })).toHaveAttribute("href", "/");
    expect(document.title).toBe("Page not found - FindMyThing");
  });

  it("navigates client-side and moves focus to <main> for keyboard and screen-reader users", async () => {
    const user = userEvent.setup();
    const router = renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const target = nav.querySelector('a[href="/sign-in"]') as HTMLAnchorElement;
    await user.click(target);
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("marks the current page in the navigation", () => {
    renderAt("/sign-in");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("guards student-only routes against unauthenticated users", () => {
    renderAt("/reports/new", mockAuthValue({ state: { status: "anonymous" } }));
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
  });

  it("renders moderator-only routes when authenticated as moderator", () => {
    const modAuth = mockAuthValue({
      state: {
        status: "authenticated",
        user: {
          user_id: "mod-1",
          email: "mod@campus.edu",
          display_name: "Campus Mod",
          role: "MODERATOR",
        },
      },
    });
    renderAt("/moderator", modAuth);
    expect(screen.getByRole("heading", { level: 1, name: "Claims review queue" })).toBeInTheDocument();
  });

  it("guards moderator routes against students", () => {
    const studentAuth = mockAuthValue({
      state: {
        status: "authenticated",
        user: {
          user_id: "student-1",
          email: "student@campus.edu",
          display_name: "Alice",
          role: "STUDENT",
        },
      },
    });
    renderAt("/moderator", studentAuth);
    expect(screen.getByRole("heading", { level: 1, name: "Not available" })).toBeInTheDocument();
  });
});
