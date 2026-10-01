import { Navigate, Route, Routes } from "react-router-dom";

import MobileApp from "./mobile/MobileApp";
import OpsApp from "./ops/OpsApp";

export default function App() {
  return (
    <Routes>
      <Route path="/m/*" element={<MobileApp />} />
      <Route path="/ops/*" element={<OpsApp />} />
      <Route path="*" element={<Navigate to="/m" replace />} />
    </Routes>
  );
}
