import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { BetSlipProvider } from './context/BetSlipContext'
import { WalletProvider } from './context/WalletContext'
import { AppLayout } from './layouts/AppLayout'
import { GameDetailPage } from './pages/GameDetailPage'
import { HomePage } from './pages/HomePage'
import { MLBGameDetailPage } from './pages/MLBGameDetailPage'
import { MLBPage } from './pages/MLBPage'
import { MyBetsPage } from './pages/MyBetsPage'
import { ParlayDetailPage } from './pages/ParlayDetailPage'
import { SignupPage } from './pages/SignupPage'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <WalletProvider>
        <BetSlipProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/mlb" element={<MLBPage />} />
              <Route path="/mlb/games/:gameId" element={<MLBGameDetailPage />} />
              <Route path="/games/:gameId" element={<GameDetailPage />} />
              <Route path="/bets/open" element={<MyBetsPage />} />
              <Route path="/bets/settled" element={<MyBetsPage />} />
              <Route path="/bets" element={<Navigate to="/bets/open" replace />} />
              <Route path="/parlays/:parlayId" element={<ParlayDetailPage />} />
              <Route path="/signup" element={<SignupPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BetSlipProvider>
      </WalletProvider>
    </BrowserRouter>
  )
}
