import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { BetSlipProvider } from './context/BetSlipContext'
import { AppLayout } from './layouts/AppLayout'
import { GameDetailPage } from './pages/GameDetailPage'
import { HomePage } from './pages/HomePage'
import { ParlayDetailPage } from './pages/ParlayDetailPage'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <BetSlipProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/games/:gameId" element={<GameDetailPage />} />
            <Route path="/parlays/:parlayId" element={<ParlayDetailPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BetSlipProvider>
    </BrowserRouter>
  )
}
