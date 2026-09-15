import { RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { router } from '@/app/router'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={150}>
        <div className="min-h-screen bg-background text-foreground">
          <RouterProvider router={router} />
        </div>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

export default App
