import Inferno from 'inferno';
import Component from 'inferno-component';
import axios from 'axios';

import ChalToolbar from './ChalToolbar';
import ChalGrid from './ChalGrid';

import './Chalboard.scss';

class Chalboard extends Component {
  constructor(props) {
    super(props);

    this.state = {
      loadingChals: true,
      loadingSolves: true,
      challenges: [],
      solves: [],
      challengeCategories: [],
      categoryFilters: [],
      completedOptions: [
        { label: 'Completed', value: 'completed' },
        { label: 'Not Completed', value: 'not_completed' }
      ],
      completedFilters: [
        { label: 'Completed', value: 'completed' },
        { label: 'Not Completed', value: 'not_completed' }
      ],
      totalPoints: 1,
      solvedPoints: 0
    };

    this.loadChals = this.loadChals.bind(this);
    this.loadSolves = this.loadSolves.bind(this);
    this.getChals = this.getChals.bind(this);
    this.isSolved = this.isSolved.bind(this);
    this.updateCategoryFilters = this.updateCategoryFilters.bind(this);
    this.updateCompletedFilters = this.updateCompletedFilters.bind(this);
  }

  componentWillMount() {
    this.loadChals();
    this.loadSolves();
  }

  async loadChals() {
    const challenges = (await axios.get('/chals')).data.game;

    this.setState(state => {
      let points = 0;

      state.challenges = challenges;

      state.challengeCategories = [
        ...challenges.reduce((set, chal) => {
          points += chal.value;
          set.add(chal.category);
          return set;
        }, new Set())
      ]
        .sort()
        .map(category => ({
          label: category,
          value: category
        }));

      state.categoryFilters = state.challengeCategories;

      state.totalPoints = points;

      state.loadingChals = false;
    });
  }

  async loadSolves() {
    const solves = (await axios.get('/solves')).data.solves;

    const solvedPoints = solves.reduce((points, solve) => {
      points += solve.value;
      return points;
    }, 0);

    this.setState(state => {
      state.solves = solves;
      state.solvedPoints = solvedPoints;
      state.loadingSolves = false;
    });
  }

  getChals() {
    const categoryFilters = this.state.categoryFilters.map(f => f.value);
    const completedFilters = this.state.completedFilters.map(f => f.value);
    return this.state.challenges.filter(chal => {
      return (
        categoryFilters.includes(chal.category) &&
        completedFilters.includes(this.isSolved(chal.id) ? 'completed' : 'not_completed')
      );
    });
  }

  isSolved(chalid) {
    return this.state.solves.map(s => s.chalid).includes(chalid);
  }

  updateCategoryFilters(categories) {
    this.setState(state => {
      state.categoryFilters = categories;
    });
  }

  updateCompletedFilters(completedFilters) {
    this.setState(state => {
      state.completedFilters = completedFilters;
    });
  }

  render() {
    return (
      <div className="chalboard container">
        <ChalToolbar
          categories={this.state.challengeCategories}
          categoryFilters={this.state.categoryFilters}
          onUpdateCategoryFilters={this.updateCategoryFilters}
          completedOptions={this.state.completedOptions}
          completedFilters={this.state.completedFilters}
          onUpdateCompletedFilters={this.updateCompletedFilters}
          progressLoading={this.state.loadingChals || this.state.loadingSolves}
          totalPoints={this.state.totalPoints}
          solvedPoints={this.state.solvedPoints}
        />
        <ChalGrid challenges={this.getChals()} solves={this.state.solves} loading={this.state.loadingChals} />
      </div>
    );
  }
}

Inferno.render(<Chalboard />, document.getElementById('challenges-container'));
