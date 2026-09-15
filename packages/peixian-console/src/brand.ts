import project from "../../../framework/project.json"

export const brand = {
  name: project.display_name,
  tagline: project.tagline,
  mark: Array.from(project.display_name.trim())[0] ?? "A",
  themeKey: `${project.project_id}-theme`,
}
