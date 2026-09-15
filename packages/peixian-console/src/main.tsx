import { render } from "solid-js/web"
import App from "./App"
import { brand } from "./brand"
import "../../ui/src/styles/theme.css"
import "./styles.css"
document.title = brand.name
render(() => <App />, document.getElementById("root")!)
